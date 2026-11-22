"""Pair exact signed dispatch recovery with two independent positive-zero materializations."""

import re

from .balanced_clamp_predicates import _LUI, _ORI, _bits
from .balanced_signed_selector_increment import _HELPER
from .compiler_phase_repairs import fresh
from .integer_repair_support import IDENT, NUMBER, edit, integer, locals_for, refs
from .operand_lifetime_repairs import _typed_locals, _visible
from .pattern_repairs import close

FAMILY = 'balanced_selector_zero_materialization'
_FLOAT = r'\d+\.\d+[fF]'
_CALL = re.compile(rf'jal ({IDENT})')
_SIGNED_BYTE = re.compile(rf'lb \$v0, ({NUMBER})(\(\$\w+\))')
_ZERO = re.compile(r'mtc1 \$zero, (\$f\d+)')
_MOVE = re.compile(r'mov\.s (\$f\d+), (\$f\d+)')
_SQUARE = re.compile(r'mul\.s (\$f\d+), (\$f\d+), \2')
_SELECTOR = re.compile(
    rf'(?m)^[ \t]*(?P<name>{IDENT})\s*=\s*\*\(\s*\(\s*s16\s*\*[^;{{}}\n]+;\s*'
    rf'switch\s*\(\s*(?P=name)\s*\)\s*{{'
)
_DECREMENT = re.compile(
    rf'(?m)^(?P<pad>[ \t]*)(?P<old>{IDENT})\s*=\s*(?P<helper>{IDENT})\('
    rf'\s*\(char\s*\*\)\s*(?P<base>{IDENT})\s*,\s*(?P<offset>{NUMBER})\s*\)\s*;\s*'
    rf'if\s*\(\s*(?P=old)\s*!=\s*0\s*\)\s*{{\s*'
    rf'(?P<field>\*\(\(s8\s*\*\)\s*\(\(\(char\s*\*\)\s*(?P=base)\)\s*\+\s*'
    rf'(?P<write_offset>{NUMBER})\s*\)\s*\))\s*=\s*\(s8\)\s*'
    rf'\(\s*(?P=old)\s*-\s*1\s*\)\s*;\s*}}'
)
_DUPLICATES = re.compile(
    rf'(?m)^(?P<pad>[ \t]*)if\s*\(\s*(?P<guard>{IDENT})\s*\)\s*{{(?P<left>[^{{}}]+)}}'
    rf'\s*else\s*{{(?P<right>[^{{}}]+)}}'
)
_FACTOR = re.compile(
    rf'(?m)^(?P<binding>[ \t]*(?P<square>{IDENT})\s*=\s*(?P<axis>{IDENT})\s*\*\s*(?P=axis)\s*;\s*\n)'
    rf'[ \t]*if\s*\(\s*(?P=axis)\s*>\s*0\.0[fF]\s*\)\s*{{\s*'
    rf'(?P<block>{{\s*)?(?P=axis)\s*=\s*(?P<positive_square>(?P=square))\s*\*\s*(?P<positive>{_FLOAT})'
    rf'\s*;(?(block)\s*}})\s*}}'
    rf'\s*else\s*{{\s*(?P=axis)\s*=\s*(?P<negative_square>(?P=square))\s*\*\s*'
    rf'\(\s*-(?P<negative>{_FLOAT})\s*\)\s*;\s*}}'
)
_FALLBACK = re.compile(
    rf'(?m)^[ \t]*if\s*\(\s*(?P<test>{IDENT})\([^;{{}}\n]+\)\s*<=\s*{_FLOAT}\s*\)\s*{{\s*'
    rf'{IDENT}\s*=\s*\*[^;{{}}\n]+;\s*{IDENT}\s*=\s*{NUMBER}\s*;\s*'
    rf'(?P<clear>(?P<value>{IDENT})\s*=\s*(?P<zero>0\.0[fF])\s*;)\s*'
    rf'(?P<call>{IDENT})\([^;{{}}\n]+\)\s*;\s*\*[^;{{}}\n]+;\s*}}\s*else\s*{{'
)
_POSITIVE_TEST = re.compile(
    rf'(?m)^(?P<pad>[ \t]*)if\s*\(\s*!\(\s*(?P<value>{IDENT})\s*>\s*(?P<zero>0\.0[fF])\s*\)\s*\)'
)
_SLOT = re.compile(rf'(?m)^[ \t]*(?P<slot>(?:u32|unsigned\s+int)\s+(?P<member>{IDENT})\s*\[\s*1\s*\]\s*;)'
                   rf'\s*}}\s*(?P<frame>{IDENT})\s*;')


def _countdowns(rows):
    for index, (op, current) in enumerate(rows[:-4]):
        load = _SIGNED_BYTE.fullmatch(op)
        if (not load or op != current or not rows[index + 1][0].startswith('beqz $v0, ')
                or rows[index + 2] != ('move $v1, $v0', '')
                or rows[index + 3] != ('addiu $v0, $v1, -1', 'addiu $v0, $v0, -1')):
            continue
        store = f'sb $v0, {load[1]}{load[2]}'
        if rows[index + 4] == (store, store):
            yield index, integer(load[1])


def _factor_at(rows, index):
    upper = _LUI.fullmatch(rows[index][0])
    lower = _ORI.fullmatch(rows[index + 1][0])
    return integer(upper[1]) << 16 | integer(lower[1]) if upper and lower else None


def _factor_sites(rows, raw, positions):
    for index in range(4, len(rows) - 12):
        op, actual = rows[index]
        square = _SQUARE.fullmatch(op)
        if (not square or op != actual or not rows[index - 1][0].startswith('bc1f ')
                or not rows[index + 6][0].startswith('mul.s ')
                or not rows[index + 5][0].startswith('j ')):
            continue
        following = [line for _, _, line in raw[positions[index]+1:positions[index + 8]]]
        if not any(line.startswith('sll $v0, $s0, ') for line in following):
            continue
        positive, negative = _factor_at(rows, index + 1), _factor_at(rows, index + 7)
        if positive is not None and negative is not None:
            yield index, positive, negative


def _zero_sites(rows):
    for index in range(14, len(rows) - 5):
        expected, current = rows[index]
        zero, copy = _ZERO.fullmatch(expected), _MOVE.fullmatch(current)
        if not zero or zero[1] == '$f0' or not copy or copy[1] != zero[1] or rows[index + 1] != ('nop', ''):
            continue
        consumer = _CALL.fullmatch(rows[index + 2][0])
        calls = [m[1] for op, actual in rows[index - 14:index] if op == actual and (m := _CALL.fullmatch(op))]
        if not consumer or rows[index + 2][0] != rows[index + 2][1] or len(calls) != 1:
            continue
        for i in range(index + 8, min(index + 75, len(rows) - 2)):
            compare = re.fullmatch(r'c\.lt\.s \$f0, (\$f\d+)', rows[i + 2][0])
            if (rows[i:i + 2] == [('mtc1 $zero, $f0', ''), ('nop', '')] and compare
                    and rows[i + 2][1] == f'c.lt.s {copy[2]}, {compare[1]}'):
                yield index, calls[0], consumer[1]


def _evidence(rows):
    positions = [i for i, (_, a, _) in enumerate(rows) if a]
    aligned = [(rows[i][1], rows[i][2]) for i in positions]
    return {(offset, positive, negative, check, call)
            for start, offset in _countdowns(aligned)
            for square, positive, negative in _factor_sites(aligned, rows, positions)
            for zero, check, call in _zero_sites(aligned) if start < square < zero and zero - start < 480}


def _selector_edits(source, part, selector, scope_end, integer_decls, macros):
    local = selector['name']
    declaration = integer_decls.get(local)
    if not declaration or declaration['type'] != 's16' or local in macros or len(refs(part, declaration)) != 4:
        return []
    start = selector.end()
    sites = [m for m in _DUPLICATES.finditer(part.clean, start, scope_end) if m['guard'] == local]
    if len(sites) != 2:
        return []
    changes = []
    for site in sites:
        body = source[site.start('left'):site.end('left')]
        left = body.strip().splitlines()
        right = source[site.start('right'):site.end('right')].strip().splitlines()
        left, right = [line.strip() for line in left], [line.strip() for line in right]
        if left != right or re.search(r'[:#\\]|\b(?:typedef|static|union|struct)\b', ' '.join(left)):
            return []
        pad = site['pad']
        changes.append((site.start(), site.end(), f'{pad}{{{body}}}'))
    return changes


def _zero_edits(source, part, context, fallback, limit, floats, macros):
    value = fallback['value']
    if value not in floats or value in macros:
        return []
    stop = close(part.clean, fallback.end() - 1, '{', '}')
    if not stop or stop > limit:
        return []
    tests = list(_POSITIVE_TEST.finditer(part.clean, fallback.end(), stop))
    slots = list(_SLOT.finditer(part.clean, part.opening + 1, part.end))
    if len(tests) != 1 or len(slots) != 1:
        return []
    test, slot = tests[0], slots[0]
    frame, member = slot['frame'], slot['member']
    if (test['value'] not in floats or {test['value'], frame, member} & macros
            or len(re.findall(rf'\b{member}\b', part.body)) != 1
            or re.search(rf'\b{frame}\b(?!\s*\.)', part.clean[slot.end():part.end])):
        return []
    struct_end = part.clean.index('}', slot.end('slot'))
    records = (part.opening + match.end() - 1
               for match in re.finditer(r'\bstruct\s*{', part.clean[part.opening:slot.start()]))
    if not any(close(part.clean, opening, '{', '}') == struct_end + 1 for opening in records):
        return []
    field = fresh(context, '', 'repair_branch_zero')
    ref = f'{frame}.{field}'
    clear_pad = re.match('[ \t]*', source[source.rfind('\n', 0, fallback.start('clear')) + 1:])[0]
    reset = f'{ref} = 0.0f;'
    return [
        (*slot.span('slot'), f'volatile float {field};'),
        (fallback.start('clear'), fallback.start('clear'), reset + '\n' + clear_pad),
        (*fallback.span('zero'), ref),
        (test.start(), test.start(), test['pad'] + reset + '\n'),
        (*test.span('zero'), ref),
    ]


def variants(source, name, rows, *, header='', max_bytes=65536):
    required = _evidence(rows)
    visible = _visible(source, name, header) if required else None
    if not visible:
        return []
    part, context = visible
    macros = set(re.findall(rf'(?m)^[ \t]*#\s*(?:define|undef)\s+({IDENT})', context))
    kinds = {'s8': {'signed char'}, 's16': {'signed short', 'short', 'short int', 'signed short int'},
             'u32': {'unsigned int', 'unsigned'}, 'f32': {'float'}}
    typedefs = re.findall(r'\btypedef\s+([^;{}]+?)\s+(s8|s16|u32|f32)\s*;', context)
    if (macros & kinds.keys() or any(' '.join(value.split()) not in kinds[kind] for value, kind in typedefs)
            or re.search(r'(?m)^\s*#\s*pragma\s+STDC\s+FENV_ACCESS\s+ON', context)):
        return []
    ints = {decl['name']: decl for decl in locals_for(part)}
    helpers = {match['fn'] for match in _HELPER.finditer(context)}
    candidates = []
    for countdown in _DECREMENT.finditer(part.clean, part.opening + 1, part.end):
        declaration = ints.get(countdown['old'])
        if (not declaration or declaration['type'] != 's8' or countdown['helper'] not in helpers
                or macros & set(re.findall(IDENT, countdown[0])) or len(refs(part, declaration)) != 3):
            continue
        offset = integer(countdown['offset'])
        if offset != integer(countdown['write_offset']) or not any(witness[0] == offset for witness in required):
            continue
        sel = _SELECTOR.match(part.clean, part.clean.find('\n', countdown.end()) + 1)
        if not sel:
            continue
        stop = close(part.clean, sel.end() - 1, '{', '}')
        changes = _selector_edits(source, part, sel, stop, ints, macros) if stop else []
        if not changes:
            continue
        pad, field = countdown['pad'], countdown['field']
        changes.append((*countdown.span(), f'{pad}if ({field} != 0)\n{pad}{{\n{pad}  ({field})--;\n{pad}}}'))
        candidates.append((offset, sel['name'], edit(source, changes)))
    if len(candidates) != 1:
        return []
    offset, selector, source = candidates[0]
    part, context = _visible(source, name, header)
    switches = [m for m in _SELECTOR.finditer(part.clean) if m['name'] == selector]
    if len(switches) != 1:
        return []
    switch = switches[0]
    stop = close(part.clean, switch.end() - 1, '{', '}')
    if not stop:
        return []
    floats = _typed_locals(part, r'(?:f32|float)')
    proposals = []
    for factor in _FACTOR.finditer(part.clean, switch.end(), stop):
        square, axis = factor['square'], factor['axis']
        if (axis not in floats or square not in floats or macros & set(re.findall(IDENT, factor[0]))
                or len(re.findall(rf'\b{square}\b', part.body)) != 4):
            continue
        pos, neg = _bits(factor['positive']), _bits('-' + factor['negative'])
        for fallback in _FALLBACK.finditer(part.clean, factor.end(), min(factor.end() + 9000, stop)):
            if not (offset, pos, neg, fallback['test'], fallback['call']) in required:
                continue
            changed = _zero_edits(source, part, context, fallback, stop, floats, macros)
            if not changed:
                continue
            inline = f'({axis} * {axis})'
            changed.extend([(*factor.span('binding'), ''), (*factor.span('positive_square'), inline),
                            (*factor.span('negative_square'), inline)])
            corrected = edit(source, changed)
            if len(corrected.encode()) <= max_bytes:
                proposals.append((FAMILY, corrected))
    return proposals if len(proposals) == 1 else []
