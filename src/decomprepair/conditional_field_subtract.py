"""Reuse a proven saved field local in a later conditional double and subtract."""

import re

from .clamp_return_local import _field
from .integer_repair_support import IDENT, NUMBER, edit, integer
from .local_flow import Flow
from .operand_lifetime_repairs import _in_scope, _typed_locals, _visible
from .trig_axis_reuse import _DECL, _FIELD, _GLOBAL, _PRIOR, _SAVED, _confirmed_global_loads

FAMILY = 'conditional_saved_field_subtract'
_FPR = r'\$f(?:[12]?[0-9]|3[01])'
_LOAD = re.compile(rf'lwc1 ({_FPR}), ({NUMBER})(\(\$\w+\))')
_GUARD = re.compile(rf'lbu (\$\w+), %lo\(({IDENT})\)\(\1\)')
_SOURCE = re.compile(
    rf'(?m)^[ \t]*(?P<input>{IDENT})\s*=\s*(?P<field>{_FIELD})\s*;\s*'
    rf'if\s*\(\s*(?P<guard>{IDENT})\s*!=\s*0\s*\)\s*\{{\s*(?P=input)\s*\*=\s*2\.0[fF]\s*;\s*\}}\s*'
    rf'(?:{IDENT}\s*=\s*0\s*;\s*)?(?P<global>{IDENT})\s*-=\s*(?P<sub>(?P=input))\s*;'
)


def _evidence(rows):
    targets = [(i, left, right) for i, (_, left, right) in enumerate(rows) if left]
    prior = list(_confirmed_global_loads(targets))
    witnessed = set()
    for j in range(1, len(targets) - 5):
        position, op, right = targets[j]
        load, other = _LOAD.fullmatch(op), _LOAD.fullmatch(right)
        guard = _GUARD.fullmatch(targets[j - 1][1])
        if not (load and other and guard and re.fullmatch(_SAVED, load[1])
                and load[1] != other[1] and load.groups()[1:] == other.groups()[1:]):
            continue
        left = [entry[1] for entry in targets[j + 1:j + 6]]
        if not left[0].startswith(f'bnel {guard[1]}, ') or left[1] != f'add.s {load[1]}, {load[1]}, {load[1]}':
            continue
        relocation = _GLOBAL.fullmatch(left[3])
        if not relocation or left[4] != f'sub.s {relocation[1]}, {relocation[1]}, {load[1]}':
            continue
        candidate = [entry[2] for entry in targets[j + 1:j + 6]]
        if not {f'add.s {other[1]}, {other[1]}, {other[1]}',
                f'sub.s {relocation[1]}, {relocation[1]}, {other[1]}'} <= set(candidate):
            continue
        offset = integer(load[2])
        if any(start < position and (register, old, symbol) == (load[1], offset, relocation[2])
               for start, register, old, symbol in prior):
            witnessed.add((offset, guard[2], relocation[2]))
    return witnessed


def variants(source, name, rows, *, header=''):
    witness = _evidence(rows)
    visible = _visible(source, name, header) if witness else None
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
    prefix = part.clean[:part.opening]
    prior = [(m, field) for m in _PRIOR.finditer(part.clean, part.opening + 1, part.end)
             if (field := _field(m['field'], prefix))]
    proposals = []
    for m in _SOURCE.finditer(part.clean, part.opening + 1, part.end):
        old = m['input']
        field = _field(m['field'], prefix)
        finish = flow.at(m.start('global'))
        begin = part.clean[part.opening + 1:m.start()].rstrip()
        if (not field or (field[1], m['guard'], m['global']) not in witness or old not in flow.names
                or field[0] == old or not finish or macros & set(re.findall(IDENT, m[0]))
                or (begin and begin[-1] not in ';{}:')):
            continue
        if any(old in flow.nodes[index].live for index in finish.successors):
            continue
        uses = list(re.finditer(rf'\b{old}\b', m[0]))
        if len(uses) != 3:
            continue
        for first, earlier in prior:
            carry = first['local']
            if (first.end() >= m.start() or first['global'] != m['global'] or earlier != field
                    or carry not in flow.names or re.search(rf'\b{carry}\b', m[0])
                    or macros & set(re.findall(IDENT, first[0]))
                    or not _in_scope(part, declarations[carry].start(), m.start())
                    or not flow.dead(carry, m.start('input'))):
                continue
            changed = edit(source, [(m.start() + use.start(), m.start() + use.end(), carry) for use in uses])
            if all(previous != changed for _, previous in proposals):
                proposals.append((FAMILY, changed))
            if len(proposals) == 4:
                return proposals
    return proposals
