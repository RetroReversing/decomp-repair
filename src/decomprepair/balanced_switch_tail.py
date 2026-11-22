"""Pair short measured instruction gains and losses before a later jump table."""

import re

from .goto_structure_repairs import parse
from .integer_repair_support import IDENT, NUMBER, edit, integer, locals_for
from .operand_lifetime_repairs import _in_scope, _typed_locals, _visible
from .pattern_repairs import close
from .switch_case_order_repairs import LABEL, _depth

FAMILY = 'balanced_switch_tail_layout'
JOIN = 'repair_shared_case_tail'
REG = r'\$\w+'
WORD = r'(?:0[xX][0-9a-fA-F]+|\d+)'

_CALL = re.compile(rf'jal ({IDENT})')
_RETURN_MOVE = re.compile(r'mov\.s (\$f(?:2[02468]|30)), \$f0')
_SAVED_COPY = re.compile(r'mov\.s (\$f(?:2[02468]|30)), (\$f(?:2[02468]|30))')
_SHIFT = re.compile(rf'sll ({REG}), ({REG}), ({WORD})')
_STORE = re.compile(rf'(?:sw|sb) ({REG}), ({WORD})\(({REG})\)')
_SLOT = re.compile(rf'\+\s*({NUMBER})\s*\)')
_SCOPE = re.compile(r'\bswitch\s*\(')
_FLOAT = r'(?:\d+(?:\.\d*)?|\.\d+)[fF]'
_SEED = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)(?P<input>{IDENT})\s*=\s*'
    rf'(?P<call>(?P<callee>{IDENT})\(\s*{IDENT}\s*,\s*(?P<a>{NUMBER})\s*,\s*(?P<b>{NUMBER})\s*\))\s*;\n'
    rf'(?P=indent)(?P<acc>(?:var|temp)_fs[0-5](?:_\d+)?)\s*=\s*(?P<product>'
    rf'(?:\(\s*(?P=input)\s*\*\s*(?P=input)\s*\)\s*\*\s*{_FLOAT}|'
    rf'(?P=input)\s*\*\s*(?:{_FLOAT}|(?P=input))))\s*;'
)
_SCALE = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)(?P<index>{IDENT})\s*=\s*(?P<scale>'
    rf'(?P<mode>{IDENT})\s*\*\s*(?P<width>{NUMBER}))\s*;[ \t]*\n'
    rf'(?P=indent)if\s*\((?P<left>[^;\n{{}}]+?)\|\|\s*\(\(\s*(?P=index)\s*=\s*(?P=scale)\s*,\s*'
)


def _defined_constant_mode(part, name, step):
    refs = re.findall(rf'\b{name}\s*=\s*([^;]+);', part.body)
    if not refs or not all(re.fullmatch(NUMBER, value.strip()) and integer(value.strip()) * step <= 32767
                           for value in refs):
        return False
    return not re.search(rf'&\s*\(*\s*{name}\b|\b{name}\s*(?:\+\+|--|[-+*/%&|^]=)|'
                         rf'(?:\+\+|--)\s*{name}\b', part.body)


def _deferred_index(part, target, prior, locals_):
    wanted = []
    for pos in range(1, len(target)):
        first = _SHIFT.fullmatch(target[pos][1])
        if not first or not 0 < int(first[3], 0) < 6 or not target[pos - 1][1].startswith('bnez '):
            continue
        tail = target[pos + 1:pos + 16]
        for (_, branch), (flag, line) in zip(tail, tail[1:]):
            if flag and line == target[pos][1] and branch.startswith('bc1f '):
                if any((old := _SHIFT.fullmatch(text)) and old.group(2, 3) == first.group(2, 3) and old[1] != first[1]
                       for changed, text in prior if changed):
                    wanted.append(1 << int(first[3], 0))
                break
    edits = []
    for match in _SCALE.finditer(part.clean, part.opening + 1, part.end):
        mode, index, step = match['mode'], match['index'], integer(match['width'])
        if step not in wanted or mode == index or any(locals_.get(name) not in ('s32', 'int') for name in (mode, index)):
            continue
        before = part.clean[part.opening + 1:match.start()].rstrip()
        if before[-1:] not in (';', '{', '}', ':'):
            continue
        opening = match.start('left') - 1
        end = close(part.clean, opening)
        block = re.match(r'\s*\{', part.clean[end:]) if end else None
        if not block or not _defined_constant_mode(part, mode, step):
            continue
        brace = end + block.end() - 1
        stop = close(part.clean, brace, '{', '}')
        use = re.compile(rf'\b{index}\b')
        if not stop or len(use.findall(part.body)) != 4 or len(use.findall(part.clean[brace:stop])) != 1:
            continue
        body = part.clean[brace:stop]
        if re.search(r'\b(?:case|default|goto|asm|__asm__)\b|(?m:^[ \t]*\w+:)', body):
            continue
        assignment = f'{index} = {match["scale"]};'
        guard = part.source[match.start('left'):match.end()]
        cleaned = re.sub(rf'\(\(\s*{index}\s*=\s*{re.escape(match["scale"])}\s*,\s*$', '((', guard)
        if cleaned == guard or re.search(r'/[*/]|#', part.source[match.start():match.end()]):
            continue
        edits.append((match.start(), brace + 1,
                      f'{match["indent"]}if ({cleaned}{part.source[match.end():brace + 1]}'
                      f'\n{match["indent"]}  {assignment}'))
    return edits


def _constant_args(window):
    args = {}
    for line in window:
        if match := re.fullmatch(rf'addiu \$(a[12]), \$zero, ({WORD})', line):
            args[match[1]] = integer(match[2])
        elif match := re.fullmatch(r'move \$(a[12]), \$zero', line):
            args[match[1]] = 0
    return args.get('a1'), args.get('a2')


def _saved_result_sites(part, target):
    call_keys = set()
    for i, (_, line) in enumerate(target):
        call = _CALL.fullmatch(line)
        if not call:
            continue
        tail = target[i + 2:i + 9]
        move = next(((i, m[1], flag) for i, (flag, op) in enumerate(tail) if (m := _RETURN_MOVE.fullmatch(op))), None)
        if not move or not any((m := _SAVED_COPY.fullmatch(op)) and m[2] == move[1] and m[1] != m[2]
                               and (move[2] or flag) for flag, op in tail[move[0] + 1:]):
            continue
        window = [op for _, op in target[max(0, i - 4):i + 2]]
        call_keys.add((call[1], *_constant_args(window)))
    floats = _typed_locals(part, r'(?:f32|float)')
    out = []
    for m in _SEED.finditer(part.clean, part.opening + 1, part.end):
        src, acc = m['input'], m['acc']
        key = (m['callee'], integer(m['a']), integer(m['b']))
        if (key not in call_keys or src == acc
                or any(var not in floats or not _in_scope(part, floats[var][1], m.start()) for var in (src, acc))):
            continue
        if re.search(rf'&\s*\(*\s*(?:{src}|{acc})\b', part.body):
            continue
        start = part.clean[part.opening + 1:m.start()].rstrip()
        if start[-1:] not in (';', '{', '}', ':') or re.search(r'/[*/]|#', part.source[m.start():m.end()]):
            continue
        product = re.sub(rf'\b{src}\b', acc, m['product'])
        pad = m['indent']
        out.append((m.start(), m.end(), f'{pad}{acc} = {m["call"]};\n{pad}{src} = {acc};\n{pad}{acc} = {product};'))
    return out


def _tail_witness(target, prior, prefix_callee, shared_callee, offsets):
    def stores(rows):
        return {int(m[2], 0) for _, op in rows if (m := _STORE.fullmatch(op))}

    for pos, (_, op) in enumerate(target):
        if op != f'jal {shared_callee}' or pos < 8:
            continue
        window = target[pos - 8:pos + 2]
        if (offsets <= stores(window) and any(line == f'jal {prefix_callee}' for _, line in window)
                and any(flag and line.startswith('j ') for flag, line in window)):
            old = [(flag, line) for flag, line in prior if flag]
            if offsets <= stores(old):
                return True
    return False


def _shared_tail(part, target, prior):
    rewrites = []
    for switch in _SCOPE.finditer(part.clean, part.opening + 1, part.end):
        after = close(part.clean, switch.end() - 1)
        brace = re.match(r'\s*\{', part.clean[after:]) if after else None
        if not brace:
            continue
        start = after + brace.end()
        end = close(part.clean, start - 1, '{', '}')
        if not end:
            continue
        labels = [m for m in LABEL.finditer(part.clean, start, end - 1) if _depth(part.clean, start, m.start()) == 0]
        boundaries = [m.start() for m in labels] + [end - 1]
        for index, (first, second) in enumerate(zip(labels, labels[1:])):
            if not all(m['value'] and re.fullmatch(NUMBER, m['value']) for m in (first, second)):
                continue
            try:
                a = parse(part.clean, first.end(), second.start())
                b = parse(part.clean, second.end(), boundaries[index + 2])
            except ValueError:
                continue
            if len(a) < 5 or len(b) != 5 or any(part.clean[x[-1].start:x[-1].end].strip() != 'break;' for x in (a, b)):
                continue
            suffix, earlier = b[-4:], a[-4:]
            pairs = [(part.clean[x.start:x.end], part.clean[y.start:y.end]) for x, y in zip(earlier, suffix)]
            if not all(''.join(x.split()) == ''.join(y.split()) for x, y in pairs):
                continue
            prefix = part.clean[b[0].start:b[0].end]
            shared = part.clean[suffix[2].start:suffix[2].end]
            prefix_call = re.fullmatch(rf'({IDENT})\([^;{{}}]+\);', prefix)
            shared_call = re.match(rf'if\s*\(\s*({IDENT})\(', shared)
            stores = [m for x in suffix[:2] if (m := _SLOT.search(part.clean[x.start:x.end]))]
            offsets = {integer(m[1]) for m in stores}
            if (not prefix_call or not shared_call or len(offsets) != 2
                    or not _tail_witness(target, prior, prefix_call[1], shared_call[1], offsets)):
                continue
            chunks = part.source[first.end():second.start()] + part.source[second.end():b[-1].end]
            if re.search(r'''/[*/]|["'#]|\bgoto\b|(?m:^[ \t]*\w+\s*:)''', chunks):
                continue
            pad = part.source[part.source.rfind('\n', 0, suffix[0].start) + 1:suffix[0].start]
            if not pad.isspace():
                continue
            rewrites.append([(earlier[0].start, earlier[-1].end, f'goto {JOIN};'),
                             (suffix[0].start, suffix[0].start, f'{JOIN}:\n{pad}')])
    return rewrites


def variants(source, name, rows, *, header=''):
    """Combine the witnessed shared tail, saved FPR copies and deferred index."""
    view = _visible(source, name, header)
    if not view:
        return []
    part, context = view
    if re.search(rf'\b{JOIN}\b|\b(?:asm|__asm__|setjmp|longjmp)\b', part.clean):
        return []
    target = [(mark != ' ', left) for mark, left, _ in rows if left]
    prior = [(mark != ' ', right) for mark, _, right in rows if right]
    locals_ = {decl['name']: decl['type'] for decl in locals_for(part)}
    tails = _shared_tail(part, target, prior)
    loads = _deferred_index(part, target, prior, locals_)
    seeds = _saved_result_sites(part, target)
    if len(tails) != 1 or len(loads) != 1 or len(seeds) != 3:
        return []
    edits = tails[0] + loads + seeds
    macros = set(re.findall(rf'(?m)^[ \t]*#\s*(?:define|undef)\s+({IDENT})', context))
    touched = {word for start, end, replacement in edits for word in re.findall(IDENT, source[start:end] + replacement)}
    if (macros & touched
            or re.search(r'\btypedef\b[^;\n]*\bvolatile\b[^;\n]*\b(?:s32|f32)\s*;', context)):
        return []
    return [(FAMILY, edit(source, edits))]
