"""Reuse a witnessed saved float local across two projection calls."""

import re

from .clamp_return_local import _field
from .integer_repair_support import IDENT, NUMBER, edit, integer
from .local_flow import Flow
from .operand_lifetime_repairs import _in_scope, _typed_locals, _visible

FAMILY = 'saved_projection_axis_reuse'
_SAVED = r'\$f(?:20|22|24|26|28|30)'
_LOAD = re.compile(rf'lwc1 ({_SAVED}), ({NUMBER})(\(\$\w+\))')
_CALL = re.compile(rf'jal ({IDENT})')
_GLOBAL = re.compile(rf'lwc1 (\$f\d+), %lo\(({IDENT})\)\(\$at\)')
_FIELD = r'\*[^;={}\n]+?'
_DECL = re.compile(rf'\b(?P<type>f32|float)\s+(?P<name>{IDENT})\s*;')
_SOURCE = re.compile(
    rf'(?m)^[ \t]*(?P<axis>{IDENT})\s*=\s*(?P<field>{_FIELD})\s*;\s*'
    rf'(?P<first_acc>{IDENT})\s*\+=\s*\(\s*(?P=axis)\s*\*\s*(?P<first>{IDENT})\([^;{{}}\n]+\)\s*\)\s*;\s*'
    rf'(?P<second_acc>{IDENT})\s*\+=\s*\(\s*(?P=axis)\s*\*\s*(?P<second>{IDENT})\([^;{{}}\n]+\)\s*\)\s*;'
)
_PRIOR = re.compile(
    rf'(?m)^[ \t]*(?P<local>{IDENT})\s*=\s*(?P<field>{_FIELD})\s*;\s*(?P<global>{IDENT})\s*-=\s*(?P=local)\s*;'
)


def _confirmed_global_loads(targets):
    for j, (index, op, right) in enumerate(targets):
        load = _LOAD.fullmatch(op)
        if not load or op != right:
            continue
        register, offset, _ = load.groups()
        window = targets[j + 1:j + 11]
        for n, (_, line, _) in enumerate(window[:5]):
            relocation = _GLOBAL.fullmatch(line)
            if not relocation:
                continue
            subtract = f'sub.s {relocation[1]}, {relocation[1]}, {register}'
            if any(left == right == subtract for _, left, right in window[n + 1:]):
                yield index, register, integer(offset), relocation[2]


def _source_witnesses(rows):
    targets = [(i, left, right) for i, (_, left, right) in enumerate(rows) if left]
    earlier, projections = list(_confirmed_global_loads(targets)), []
    for j, (index, op, right) in enumerate(targets):
        load, candidate = _LOAD.fullmatch(op), _LOAD.fullmatch(right)
        if not load:
            continue
        register, offset, base = load.groups()
        if not candidate or candidate[1] == register or candidate.groups()[1:] != (offset, base):
            continue
        nearby = targets[j + 1:j + 25]
        first = next(((n, match[1]) for n, (_, line, _) in enumerate(nearby)
                      if (match := _CALL.fullmatch(line))), None)
        if not first or first[0] > 2:
            continue
        offset_one, name_one = first
        second = next(((n, match[1]) for n, (_, line, _) in enumerate(nearby[offset_one + 1:], offset_one + 1)
                       if (match := _CALL.fullmatch(line))), None)
        if not second or second[1] == name_one:
            continue
        offset_two, name_two = second
        multiply = f'mul.s $f0, {register}, $f0'
        alternate = f'mul.s $f0, {candidate[1]}, $f0'
        first_targets = nearby[offset_one:offset_two]
        after = nearby[offset_two:offset_two + 12]
        start = nearby[offset_one][0]
        stop = nearby[offset_two][0]
        end = after[-1][0]
        first_candidate = {right for _, _, right in rows[start:stop]}
        second_candidate = {right for _, _, right in rows[stop:end + 1]}
        if (multiply in {line for _, line, _ in first_targets} and multiply in {line for _, line, _ in after}
                and {f'jal {name_one}', alternate} <= first_candidate
                and {f'jal {name_two}', alternate} <= second_candidate):
            projections.append((index, register, integer(offset), name_one, name_two))
    return {(old_offset, symbol, field, first, second) for begin, saved, old_offset, symbol in earlier
            for end, register, field, first, second in projections if begin < end and saved == register}


def variants(source, name, rows, *, header=''):
    witnesses = _source_witnesses(rows)
    visible = _visible(source, name, header) if witnesses else None
    if not visible:
        return []
    part, context = visible
    if re.search(r'\btypedef\b[^;\n]*\b(?:volatile|_Atomic)\b[^;\n]*\bf32\s*;', context):
        return []
    ordinary = _typed_locals(part, r'(?:f32|float)')
    declarations = {m['name']: m for m in _DECL.finditer(part.clean, part.opening + 1, part.end)
                    if m['name'] in ordinary and m.start() == ordinary[m['name']][1]}
    try:
        flow = Flow(part, declarations.values())
    except (ValueError, RecursionError):
        return []
    macros = set(re.findall(rf'(?m)^[ \t]*#\s*(?:define|undef)\s+({IDENT})', context))
    prior = [(m, _field(m['field'], part.clean[:part.opening]))
             for m in _PRIOR.finditer(part.clean, part.opening + 1, part.end)]
    proposals = []
    for m in _SOURCE.finditer(part.clean, part.opening + 1, part.end):
        axis = m['axis']
        before = part.clean[part.opening + 1:m.start()].rstrip()
        if before and before[-1] not in ';{}:':
            continue
        field = _field(m['field'], part.clean[:part.opening])
        last = flow.at(m.start('second_acc'))
        if (not field or not last or axis not in flow.names or
                any(axis in flow.nodes[index].live for index in last.successors)):
            continue
        if axis in (m['first_acc'], m['second_acc']) or macros & set(re.findall(IDENT, m[0])):
            continue
        positions = list(re.finditer(rf'\b{axis}\b', m[0]))
        if len(positions) != 3:
            continue
        for previous, held in prior:
            carry = previous['local']
            if (not held or carry == axis or previous.end() >= m.start() or carry not in flow.names
                    or not _in_scope(part, declarations[carry].start(), m.start())
                    or not flow.dead(carry, m.start('axis'))):
                continue
            if re.search(rf'\b{carry}\b', m[0]) or macros & set(re.findall(IDENT, previous[0])):
                continue
            if (held[1], previous['global'], field[1], m['first'], m['second']) not in witnesses:
                continue
            bits = [(m.start() + use.start(), m.start() + use.end(), carry) for use in positions]
            changed = edit(source, bits)
            if all(other != changed for _, other in proposals):
                proposals.append((FAMILY, changed))
            if len(proposals) == 4:
                return proposals
    return proposals
