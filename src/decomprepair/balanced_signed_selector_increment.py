"""Pair a signed byte selector with an explicit saved byte increment."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, locals_for, refs
from .local_flow import Flow
from .operand_lifetime_repairs import _in_scope, _visible
from .pattern_repairs import close

FAMILY = 'balanced_signed_selector_increment'
_ADDR = rf'({NUMBER})(\(\$\w+\))'
_SIGNED_LOAD = re.compile(rf'lb \$v1, {_ADDR}')
_BYTE_STORE = re.compile(rf'sb \$v0, {_ADDR}')
_PREDICATE = re.compile(rf'slti \$v1, \$v1, ({NUMBER})')
_HELPER = re.compile(
    rf'\b(?:static\s+inline|inline\s+static)\s+s8\s+(?P<fn>{IDENT})\s*\(\s*char\s*\*\s*(?P<base>{IDENT})'
    rf'\s*,\s*int\s+(?P<index>{IDENT})\s*\)\s*\{{\s*return\s+\*\(\(s8\s*\*\)'
    r'\s*\(\s*(?P=base)\s*\+\s*(?P=index)\s*\)\s*\);\s*\}'
)
_READ = (
    rf'(?P<var>{IDENT})\s*=\s*(?P<fn>{IDENT})\(\s*\(char\s*\*\)\s*(?P<base>{IDENT})\s*'
    rf',\s*(?P<offset>{NUMBER})\s*\)\s*;\s*'
)
_MODE = re.compile(rf'(?m)^[ \t]*{_READ}switch\s*\(\s*(?P=var)\s*\)\s*\{{')
_FIELD = r'\*\(\(\s*(?P<type>[su]8)\s*\*\s*\)\s*\(\(\(\s*char\s*\*\s*\)\s*(?P=base)\s*\)'
_FIELD += rf'\s*\+\s*(?P<field_offset>{NUMBER})\s*\)\s*\)'
_COUNTER = re.compile(
    rf'(?m)^[ \t]*{_READ}'
    rf'\*\(\(\s*u8\s*\*\s*\)\s*\(\(\(\s*char\s*\*\s*\)\s*(?P=base)\s*\)'
    rf'\s*\+\s*(?P<reset_offset>{NUMBER})\s*\)\s*\)\s*=\s*{NUMBER}\s*;\s*'
    rf'^(?P<pad>[ \t]*)if\s*\(\s*(?P=var)\s*<\s*(?P<limit>{NUMBER})\s*\)\s*\{{\s*'
    rf'{_FIELD}\s*=\s*\(s8\)\s*\(\s*(?P<increment>(?P=var))\s*\+\s*1\s*\)\s*;\s*\}}'
)


def _evidence(rows):
    target = [(i, left) for i, (_, left, _) in enumerate(rows) if left]
    selectors = []
    counters = []
    for j in range(len(target) - 6):
        index, op = target[j]
        following = [line for _, line in target[j + 1:j + 7]]
        branch, first, lower, second, upper, _ = following
        selector = _SIGNED_LOAD.fullmatch(op)
        destination = branch.split()[2:3]
        if (selector and branch.startswith('bltz $v1, ') and first == 'slti $v0, $v1, 2'
                and lower.split()[:2] == ['bnez', '$v0,'] and lower.split()[2:3] == destination and second == 'slti $v0, $v1, 4'
                and upper.split()[:2] == ['beqz', '$v0,'] and upper.split()[2:3] == destination):
            current = {right for _, _, right in rows[max(0, index - 1):target[j + 3][0] + 1]}
            if f'lb $v0, {selector[1]}{selector[2]}' in current and 'andi $v1, $v0, 0xffff' in current:
                selectors.append((index, integer(selector[1])))
        load = _SIGNED_LOAD.fullmatch(op)
        reset = _BYTE_STORE.fullmatch(following[0])
        limit = _PREDICATE.fullmatch(following[2])
        if (load and reset and reset[2] == load[2] and limit and following[1] == 'move $v0, $v1'
                and following[3].startswith('beqz $v1, ') and following[4] == 'addiu $v0, $v0, 1'
                and following[5] == f'sb $v0, {load[1]}{load[2]}'):
            current = {right for _, _, right in rows[index:target[j + 6][0] + 1]}
            if (f'slti $v0, $v1, {limit[1]}' in current and 'addiu $v0, $v1, 1' in current
                    and 'move $v0, $v1' not in current):
                counters.append((index, integer(load[1]), integer(reset[1]), integer(limit[1])))
    return {(select, count, reset, limit) for first, select in selectors
            for last, count, reset, limit in counters if first < last}


def _small_cases(part, match):
    limit = close(part.clean, match.end() - 1, '{', '}')
    if not limit:
        return False
    body = part.clean[match.end():limit - 1]
    cases = re.findall(r'\bcase\s+([^:]+)\s*:', body)
    return len(cases) == 4 and all(re.fullmatch(NUMBER, label.strip()) for label in cases) and (
        {integer(label.strip()) for label in cases} == {0, 1, 2, 3}
    )


def variants(source, name, rows, *, header=''):
    witness = _evidence(rows)
    visible = _visible(source, name, header) if witness else None
    if not visible:
        return []
    part, context = visible
    if re.search(r'\btypedef\b[^;\n]*\b(?:volatile|_Atomic)\b[^;\n]*\b[su](?:8|16)\s*;', context):
        return []
    helpers = {m['fn'] for m in _HELPER.finditer(context)}
    macros = set(re.findall(rf'(?m)^[ \t]*#\s*(?:define|undef)\s+({IDENT})', context))
    locals_found = {entry['name']: entry for entry in locals_for(part) if entry['name'] not in macros}
    types = {local: entry['type'] for local, entry in locals_found.items()}
    copies = [name for name, typ in types.items() if typ in ('s16', 'short', 'signed short')]
    if not helpers or not copies:
        return []
    try:
        flow = Flow(part, locals_found.values())
    except (ValueError, RecursionError):
        return []
    modes = [m for m in _MODE.finditer(part.clean, part.opening + 1, part.end)
             if types.get(m['var']) == 'unsigned short' and m['fn'] in helpers and _small_cases(part, m)
             and len(refs(part, locals_found[m['var']])) == 2]
    proposals = []
    for m in _COUNTER.finditer(part.clean, part.opening + 1, part.end):
        count, limit = m['var'], integer(m['limit'])
        offset = integer(m['offset'])
        if (types.get(count) != 's8' or m['fn'] not in helpers or len(refs(part, locals_found[count])) != 3
                or m['type'] != 's8' or integer(m['field_offset']) != offset or not 0 < limit < 127):
            continue
        start = m.start('pad') + len(m['pad'])
        for mode in modes:
            if mode.start() >= m.start() or (integer(mode['offset']), offset, integer(m['reset_offset']), limit) not in witness:
                continue
            if macros & set(re.findall(IDENT, m[0] + mode[0])):
                continue
            decl = locals_found[mode['var']]
            if any(re.search(rf'\b(?:volatile|_Atomic)\b[^;{{}}\n]*\b{local}\b', context)
                   for local in (count, mode['var'])):
                continue
            for carry in copies:
                if (carry not in flow.names or not _in_scope(part, locals_found[carry].start(), start)
                        or not flow.dead(carry, start + 4) or carry in set(re.findall(IDENT, m[0]))):
                    continue
                pad = m['pad']
                test = f'{carry} = {count};\n{pad}{count} = ({count} < {m["limit"]});\n{pad}if ({count})'
                edits = [(*decl.span('type'), 's8'), (start, part.clean.index('{', start), test + '\n' + pad),
                         (*m.span('increment'), carry)]
                proposals.append((FAMILY, edit(source, edits)))
                if len(proposals) == 4:
                    return proposals
    return proposals
