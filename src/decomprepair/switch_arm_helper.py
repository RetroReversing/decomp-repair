"""Switch arms that differ only in their constants, written once as an inline helper with the constants passed in.

An N64 sound-sequence interpreter (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`) has nine opcodes that each append a
marker to one of nine four-entry lists: the same eleven statements per arm, with a different flag bit (`0x200000`,
`0x400000`, ...) and different list offsets. m2c writes each arm out, and with the bit a literal fold-const turns
`!(flags & 0x200000) || n == 0` into a shift-and-xor and every `&& / ||` into branches. The target instead tests
`and; sltiu; sltiu; or` with the bit held in a register that the `|=` reuses, and computes the list's base before the
test: the game called an inline function, whose parameters are variables when its body is expanded (integrate.c binds
each argument to a pseudo), so fold never sees the bit as a constant. Written as one `static inline` helper taking the
arm's varying constants, the 1315-instruction interpreter went 29955 -> 22323 (22863 with the parameters in the other
order); no change inside the arms reaches that, since the arms' literals are what fold sees.

`switch_arm_inline_helper`
    For each run of at least three consecutive top-level `case K:` arms of one `switch` whose statements are the same
    once each arm's private locals are renamed in order of appearance and every integer literal is ignored, and that
    end in the same `goto L;` or `break;`: a `static inline void` helper before the function holding the first arm's
    statements, with one parameter per literal that differs between the arms (one parameter for literals that differ
    in lockstep), the arm-private locals declared in the helper with the function's own types, and the function's
    parameters and other locals that the arms only read passed in. Each arm becomes a call followed by its
    `goto`/`break`. Children: the constants in the order they appear, and in the reverse order (the order changes
    which pseudo integrate.c makes first, and so the allocation).

The arms must not assign a variable of the function's that is read outside them, take its address, return, or contain
labels, `case`s, `break`, `continue` or `goto`: the helper's behaviour is then the arm's. The exact judge decides.
"""
import re

from .csource import _blank, find
from .integer_repair_support import IDENT, NUMBER, edit, view
from .pattern_repairs import close

FAMILY = 'switch_arm_inline_helper'
FAMILIES = (FAMILY,)
MINIMUM = 3
TOKEN = re.compile(r'0[xX][0-9a-fA-F]+[uUlL]*|\d+[uUlL]*|[A-Za-z_]\w*|->|<<=|>>=|[-+*/%&|^!=<>]=|&&|\|\||\+\+|--|<<|>>|\S')
KEYWORDS = {'if', 'else', 'while', 'do', 'for', 'switch', 'return', 'sizeof', 'struct', 'union', 'enum', 'const',
            'volatile', 'register', 'static', 'unsigned', 'signed', 'char', 'short', 'int', 'long', 'float', 'double',
            'void', 'u8', 's8', 'u16', 's16', 'u32', 's32', 'u64', 's64', 'f32', 'f64', 'NULL'}
LABEL = re.compile(r'(?<![\w?:])(?:case\b[^:]*|default\s*|' + IDENT + r'\s*):(?!:)')
ASSIGN = r'(?:[-+*/%&|^]|<<|>>)?=(?!=)'


def _number(token):
    return re.fullmatch(NUMBER, token) is not None


def _value(token):
    text = re.sub(r'[uUlL]+$', '', token)
    return int(text, 16 if text.lower().startswith('0x') else 10)


def _arms(clean, opening, end):
    """The top-level `case K:` arms of the switch body between `opening` and `end` as (case start, body start, stop)."""
    labels = []
    depth = 0
    at = opening + 1
    while at < end - 1:
        char = clean[at]
        if char in '{(':
            depth += 1
        elif char in '})':
            depth -= 1
        elif depth == 0 and clean.startswith('case', at) and not re.match(r'\w', clean[at - 1]):
            colon = clean.find(':', at)
            labels.append(('case', at, colon + 1))
        elif depth == 0 and re.match(r'default\s*:', clean[at:]) and not re.match(r'\w', clean[at - 1]):
            labels.append(('default', at, clean.find(':', at) + 1))
        at += 1
    arms = []
    for n, (kind, start, body) in enumerate(labels):
        stop = labels[n + 1][1] if n + 1 < len(labels) else end - 1
        if kind == 'case':
            arms.append((start, body, stop))
        else:
            arms.append(None)
    return arms


def _split(text):
    """An arm's statements and its closing `goto L;` / `break;`, or None."""
    stripped = text.rstrip()
    tail = re.search(r'(?:\bgoto\s+' + IDENT + r'|\bbreak)\s*;$', stripped)
    if not tail:
        return None
    core = stripped[:tail.start()]
    if (not core.strip() or LABEL.search(core) or re.search(r'\b(?:break|continue|goto|return|case|default|switch)\b', core)
            or core.count('{') != core.count('}')):
        return None
    return core, re.sub(r'\s+', ' ', tail[0])


def _declarations(clean, opening, end):
    """`name -> (type text, declaration span)` for the function's simple one-name declarations at its top level."""
    found = {}
    depth = 0
    for hit in re.finditer(r'[{}]|(?<=[;{}])\s*(?P<decl>(?:register\s+)?(?:(?:unsigned|signed|struct|union)\s+)?'
                           + IDENT + r'(?:\s+' + IDENT + r')??[\s*]+(?<![\w])(?P<name>' + IDENT + r')\s*;)',
                           clean[opening:end]):
        if hit[0] == '{':
            depth += 1
            continue
        if hit[0] == '}':
            depth -= 1
            continue
        if depth != 1 or not hit['decl']:
            continue
        decl = hit['decl']
        name = hit['name']
        kind = decl[:decl.rfind(name)].strip()
        if re.match(r'(?:return|goto|break|continue)\b', kind) or not kind:
            continue
        found[name] = (re.sub(r'^register\s+', '', kind), (opening + hit.start('decl'), opening + hit.end('decl')))
    return found


def _parameters(clean, start, opening, name):
    head = clean[start:opening]
    found = re.search(r'\b' + re.escape(name) + r'\s*\((?P<list>[^)]*)\)\s*$', head)
    if not found:
        return {}
    params = {}
    for piece in found['list'].split(','):
        piece = piece.strip()
        hit = re.search(r'(' + IDENT + r')\s*$', piece)
        if not hit or piece == 'void' or hit[1] == piece:
            continue
        params[hit[1]] = piece[:hit.start()].strip()
    return params


def _signature(tokens, private):
    names = {}
    shape = []
    for token in tokens:
        if _number(token):
            shape.append('#')
        elif token in private:
            shape.append(names.setdefault(token, f'@{len(names)}'))
        else:
            shape.append(token)
    return tuple(shape), [t for t in tokens if t in private and t in names]


def _private_order(tokens, private):
    seen = []
    for token in tokens:
        if token in private and token not in seen:
            seen.append(token)
    return seen


def _helper_name(name, key, source):
    base = f'{name}_arm_{key}'
    text = base
    n = 2
    while re.search(r'\b' + re.escape(text) + r'\b', source):
        text = f'{base}_{n}'
        n += 1
    return text


def variants(source, name):
    part = view(source, name)
    span = find(source, name)
    if not part or not span:
        return []
    clean = part.clean
    declarations = _declarations(clean, part.opening, part.end)
    parameters = _parameters(clean, span[0], part.opening, name)
    body = clean[part.opening + 1:part.end - 1]
    counts = {}
    for token in re.findall(IDENT, body):
        counts[token] = counts.get(token, 0) + 1
    results = []
    for switch in re.finditer(r'\bswitch\s*\(', clean[part.opening:part.end]):
        paren = part.opening + switch.end() - 1
        after = close(clean, paren, '(', ')')
        if not after:
            continue
        brace = re.match(r'\s*{', clean[after:])
        if not brace:
            continue
        opening = after + brace.end() - 1
        end = close(clean, opening, '{', '}')
        if not end:
            continue
        arms = []
        for arm in _arms(clean, opening, end):
            if arm is None:
                arms.append(None)
                continue
            start, body_start, stop = arm
            split = _split(clean[body_start:stop])
            if not split:
                arms.append(None)
                continue
            core, tail = split
            tokens = TOKEN.findall(core)
            arms.append({'start': start, 'body': body_start, 'core_end': body_start + len(core), 'tail': tail,
                         'tokens': tokens, 'key': re.sub(r'\W+', '', clean[start + 4:body_start - 1]).strip()})
        results.extend(_groups(source, name, arms, declarations, parameters, counts, span))
    seen = set()
    unique = []
    for family, text in results:
        if text not in seen:
            seen.add(text)
            unique.append((family, text))
    return unique


def _groups(source, name, arms, declarations, parameters, counts, span):
    runs = []
    current = []
    for arm in arms + [None]:
        if arm is not None:
            arm['private'] = {t for t in arm['tokens'] if t in declarations
                              and counts.get(t, 0) == arm['tokens'].count(t) + 1}
            arm['shape'] = _signature(arm['tokens'], arm['private'])[0] + (arm['tail'],)
        if arm is not None and current and arm['shape'] == current[0]['shape']:
            current.append(arm)
            continue
        if len(current) >= MINIMUM:
            runs.append(current)
        current = [arm] if arm is not None else []
    results = []
    for run in runs:
        for text in _apply(source, name, run, declarations, parameters, span):
            results.append((FAMILY, text))
    return results


def _apply(source, name, run, declarations, parameters, span):
    first = run[0]
    tokens = first['tokens']
    private = _private_order(tokens, first['private'])
    shared = []
    for token in tokens:
        if token in KEYWORDS or token in first['private'] or not re.fullmatch(IDENT, token):
            continue
        if (token in parameters or token in declarations) and token not in shared:
            shared.append(token)
    core = source[first['body']:first['core_end']]
    clean_core = ''.join(re.escape(t) for t in tokens)
    for variable in shared:
        # a variable of the function's that the arms write or take the address of stays where it is
        if re.search(r'(?<![\w.>])' + re.escape(variable) + r'\s*' + ASSIGN, core) or re.search(
                r'(?:\+\+|--)\s*' + re.escape(variable) + r'\b|\b' + re.escape(variable) + r'\s*(?:\+\+|--)', core) or re.search(
                r'&\s*' + re.escape(variable) + r'\b(?!\s*[\[.])', core.replace('&&', '  ')):
            return []
    for arm in run:
        if any(declarations.get(p) is None for p in arm['private']):
            return []
    outside = _blank(source[:span[0]] + source[span[1]:])
    for token in set(tokens):
        if (token in KEYWORDS or token in first['private'] or token in shared or not re.fullmatch(IDENT, token)
                or re.search(r'\b' + re.escape(token) + r'\b', outside)):
            continue
        # a name of the function's that this pass can't pass in (declared in a nested block, or with others on one
        # line) unless the arm declares it itself
        if not re.search(r'\w[\s*]+' + re.escape(token) + r'\s*[;=\[]', core):
            return []
    if not clean_core:
        return []
    positions = [n for n, t in enumerate(tokens) if _number(t)]
    vectors = []
    for n in positions:
        vectors.append(tuple(_value(arm['tokens'][n]) for arm in run))
    varying = []
    for n, vector in zip(positions, vectors):
        if len(set(vector)) > 1 and vector not in varying:
            varying.append(vector)
    if not varying:
        return []
    helper = _helper_name(name, first['key'].lower() or 'case', source)
    results = []
    for order in (varying, list(reversed(varying))):
        names = {vector: f'k{n}' for n, vector in enumerate(order)}
        text_tokens = []
        # rebuild the template from the source text so spelling and spacing survive
        pieces = re.split(r'(' + '|'.join([r'\b0[xX][0-9a-fA-F]+[uUlL]*\b', r'\b\d+[uUlL]*\b']) + r')', core)
        literal = 0
        for piece in pieces:
            if re.fullmatch(r'0[xX][0-9a-fA-F]+[uUlL]*|\d+[uUlL]*', piece or ''):
                vector = vectors[literal] if literal < len(vectors) else None
                literal += 1
                if vector in names and len(set(vector)) > 1:
                    text_tokens.append(names[vector])
                    continue
            text_tokens.append(piece)
        if literal != len(positions):
            return []
        template = ''.join(text_tokens)
        params = [f'{parameters.get(v) or declarations[v][0]} {v}' for v in shared]
        params += [f'int {names[vector]}' for vector in order]
        locals_ = ''.join(f'  {declarations[v][0]} {v};\n' for v in private)
        definition = (f'static inline void {helper}({", ".join(params) or "void"})\n{{\n{locals_}'
                      f'{_reindent(template).rstrip()}\n}}\n\n')
        edits = [(span[0], span[0], definition)]
        for arm in run:
            values = {}
            for n, vector in zip(positions, vectors):
                if vector in names:
                    values[names[vector]] = arm['tokens'][n]
            arguments = list(shared) + [values[names[vector]] for vector in order]
            edits.append((arm['body'], arm['core_end'], f'\n        {helper}({", ".join(arguments)});\n        '))
        removed = set()
        for arm in run:
            for variable in arm['private']:
                start, stop = declarations[variable][1]
                if (start, stop) not in removed:
                    removed.add((start, stop))
                    line_start = source.rfind('\n', 0, start) + 1
                    line_end = source.find('\n', stop)
                    if source[line_start:start].strip() == '' and source[stop:line_end].strip() == '':
                        edits.append((line_start, line_end + 1, ''))
                    else:
                        edits.append((start, stop, ''))
        results.append(edit(source, edits))
    return results


def _reindent(text):
    lines = [line for line in text.strip('\n').split('\n')]
    while lines and not lines[0].strip():
        lines.pop(0)
    indent = min((len(line) - len(line.lstrip()) for line in lines if line.strip()), default=0)
    return '\n'.join('  ' + line[indent:] if line.strip() else '' for line in lines)


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 90}  # the registry: no caller wiring (registry.py)
