"""Restore the target order of three independent stack-vector updates."""

import re

from .goto_structure_repairs import _paths, parse
from .integer_repair_support import IDENT, edit, view
from .mips_returns import instructions
from .pattern_repairs import close
from .stack_call_output_repairs import _ARGUMENT, _CONTROL, _KEEP, _READ
from .vector_output_capture import _buffer_uses_are_reads_or_calls, _local_array

FAMILY = 'vector_component_order'
FAMILIES = (FAMILY,)
_CALL = re.compile(rf'(?P<name>{IDENT})\s*\(\s*(?P<buf>{IDENT}(?:\.{IDENT})?)\s*,')
_UPDATE = re.compile(r'(?P<dest>var_(?:s[0-7]|fp))\s*(?P<op>[+-])=\s*(?P<rhs>[^;]+);')
_FLOAT = r'(?:f32|float)'
_MTC1 = re.compile(r'mtc1\s+(\$\w+),\s*(\$f\w+)')
_ARITHMETIC = re.compile(r'(add|sub)\.s\s+(\$f\w+),\s*\2,\s*(\$f\w+)')


def _target_order(rows, memory, desired):
    loaded, held, computed = {}, {}, {}
    ordered = []
    for row in rows:
        if _CONTROL.match(row):
            break
        if (store := _KEEP.fullmatch(row)) and (value := computed.get(store[2])):
            saved, component, operation = value
            if saved == store[1] and desired.get(component) == (saved, operation):
                if component not in ordered:
                    ordered.append(component)
        load = _READ.fullmatch(row)
        transfer = _MTC1.fullmatch(row)
        math = _ARITHMETIC.fullmatch(row)
        written = re.match(r'(?:l[wd]c1|\w+\.[sdw])\s+(\$f\w+),', row)
        result = None
        if math and math[2] in held and math[3] in loaded:
            result = (held[math[2]], loaded[math[3]], math[1])
        fpr = transfer[2] if transfer else written[1] if written else None
        if fpr:
            for values in (loaded, held, computed):
                values.pop(fpr, None)
        if load and (offset := int(load[2], 0)) in memory:
            loaded[load[1]] = memory[offset]
        if transfer:
            held[transfer[2]] = transfer[1]
        if result:
            computed[math[2]] = result
    return ordered


def _source_order(part, buffer, siblings):
    update = re.compile(rf'{re.escape(buffer)}\s*\[\s*([012])\s*\]')
    groups, operands = {}, {}
    pending = None
    for statement in siblings[:6]:
        text = part.clean[statement.start:statement.end]
        match = _UPDATE.fullmatch(text) if statement.kind == 'simple' else None
        if not match:
            break
        dest, rhs = match['dest'], match['rhs'].strip()
        if not (field := update.fullmatch(rhs)):
            if match['op'] != '+' or pending or not re.fullmatch(IDENT, rhs):
                return None
            if not re.search(rf'\bextern\s+{_FLOAT}\s+{rhs}\s*;', part.clean[:part.opening]):
                return None
            pending = (dest, statement.start)
            continue
        index = int(field[1])
        if index in groups or dest in operands or pending and pending[0] != dest:
            return None
        groups[index] = (pending[1] if pending else statement.start, statement.end)
        operands[dest] = (index, match['op'])
        pending = None
        if len(groups) == 3:
            break
    if len(groups) != 3 or any(
        not re.search(rf'(?m)^\s*{_FLOAT}\s+{dest}\s*;', part.body)
        or re.search(rf'&\s*\(*\s*{dest}\b', part.body) for dest in operands
    ):
        return None
    desired = {index: ('$'+dest[4:], 'add' if op == '+' else 'sub')
               for dest, (index, op) in operands.items()}
    return groups, desired


def variants(source, name, asm):
    part = view(source, name) if asm and 'sub.s' in asm and 'add.s' in asm else None
    if not part:
        return []
    end = close(part.clean, part.opening, '{', '}')
    if not end:
        return []
    try:
        paths = list(_paths(parse(part.clean, part.opening+1, end-1)))
    except ValueError:
        return []
    rows = instructions(asm)
    calls = {}
    for stmt, trail in paths:
        match = _CALL.match(part.clean, stmt.start, stmt.end) if stmt.kind == 'simple' else None
        if match:
            calls.setdefault(match['name'], []).append((stmt, trail, match['buf']))
    choices = []
    for callee, sites in calls.items():
        targets = [i for i, row in enumerate(rows[:-1]) if row == f'jal {callee}']
        if len(targets) != len(sites):
            continue
        for target, (_, trail, buffer) in zip(targets, sites):
            slot = _ARGUMENT.fullmatch(rows[target+1])
            if not slot or not _local_array(part.body, buffer) or not _buffer_uses_are_reads_or_calls(part, callee, buffer):
                continue
            siblings, index, _ = trail[-1]
            candidate = _source_order(part, buffer, siblings[index+1:])
            if not candidate:
                continue
            groups, desired = candidate
            base = int(slot[1], 0)
            memory = {base+4*index: index for index in range(3)}
            order = _target_order(rows[target+2:target+27], memory, desired)
            if len(order) != 3 or order == list(groups):
                continue
            spans = list(groups.values())
            separator = source[spans[0][1]:spans[1][0]]
            text = separator.join(source[slice(*groups[index])] for index in order)
            choices.append((FAMILY, edit(source, [(spans[0][0], spans[-1][1], text)])))
    return choices[:3]
