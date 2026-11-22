"""Balance an earlier float predicate with a carried, proven-zero projection accumulator."""

import re
import struct

from .balanced_float_predicate_return import _PREDICATES, _earlier
from .clamp_return_local import _field
from .compiler_phase_repairs import fresh
from .equal_value_flow import macros_safe
from .integer_repair_support import IDENT, NUMBER, edit, integer
from .local_flow import Flow
from .operand_lifetime_repairs import _escaped, _in_scope, _typed_locals, _visible

FAMILY = 'balanced_predicate_projection'
_FPR = r'\$f(?:[12]?[0-9]|3[01])'
_FIELD = re.compile(rf'lwc1 ({_FPR}), ({NUMBER})\((\$\w+)\)')
_CALL = re.compile(rf'jal ({IDENT})')
_CARRY = re.compile(r'mtc1 (\$s[0-7]|\$fp), (\$f\d+)')
_DECL = re.compile(rf'\b(?:float|f32)\s+(?P<name>{IDENT})\s*;')
_LOAD = re.compile(rf'(?m)^[ \t]*(?P<axis>{IDENT})\s*=\s*(?P<field>\*[^;{{}}\n]+)\s*;[\s]*$')
_PROJECTION = re.compile(
    rf'(?m)^[ \t]*(?P<acc>{IDENT})\s*(?P<initial>=\s*0\.0[fF]\s*\+)\s*'
    rf'\(\s*(?P<axis>{IDENT})\s*\*\s*(?P<call>{IDENT})\([^;{{}}\n]+\)\s*\)\s*;'
)
_ZERO_UNION = re.compile(
    rf'\bunion\s*\{{\s*(?:u32|unsigned\s+int)\s+(?P<bits>{IDENT})\s*;\s*'
    rf'(?:f32|float)\s+(?P<number>{IDENT})\s*;\s*\}}\s*(?P<name>{IDENT})\s*;'
)


def _evidence(rows):
    target = [(i, left) for i, (_, left, _) in enumerate(rows) if left]
    by_row = {row: n for n, (row, _) in enumerate(target)}
    result = set()
    for compare, axis, bits in _earlier(rows, target, same_comparisons=False):
        start = by_row[compare]
        load = next((m for row, op in reversed(target[max(0, start - 24):start])
                     if (m := _FIELD.fullmatch(op)) and m[1] == axis
                     and (other := _FIELD.fullmatch(rows[row][2])) and other.groups()[1:] == m.groups()[1:]), None)
        if not load:
            continue
        for i in range(start + 8, min(start + 30, len(target))):
            index, op = target[i]
            call = _CALL.fullmatch(op)
            if not call or rows[index][2] != op:
                continue
            following = target[i + 1:i + 10]
            for j, (row, line) in enumerate(following[:4]):
                if line != f'mul.s $f0, {axis}, $f0':
                    continue
                candidate_product = re.fullmatch(rf'mul\.s \$f0, ({_FPR}), \$f0', rows[row][2])
                tail = following[j + 1:]
                if not candidate_product or not tail:
                    continue
                register = _CARRY.fullmatch(tail[0][1])
                if not register or (rows[tail[0][0]][2] and not rows[tail[0][0]][2].startswith('mtc1 $zero, ')):
                    continue
                gpr, fp = register.groups()
                candidate = [rows[position][2] for position, _ in tail]
                expected = {op for _, op in tail}
                if ({f'add.s {fp}, {fp}, $f0', f'mfc1 {gpr}, {fp}'} <= expected
                        and any(re.fullmatch(rf'add\.s \$f0, \$f0, {_FPR}', line) for line in candidate)
                        and f'mfc1 {gpr}, $f0' in candidate):
                    result.add((bits, integer(load[2]), call[1]))
    return result


def _prior_references(flow, parents, index, name):
    """Find the first other reference on each incoming path, including back edges."""
    if index == flow.entry:
        return None
    pending = list(parents[index])
    seen, hits = set(), set()
    reference = re.compile(rf'\b{name}\b')
    while pending:
        node_index = pending.pop()
        if node_index == index:
            return None
        if node_index in seen:
            continue
        seen.add(node_index)
        node = flow.nodes[node_index]
        if reference.search(flow.part.clean[node.start:node.end]):
            hits.add(node_index)
        else:
            if node_index == flow.entry or not parents[node_index]:
                return None
            pending.extend(parents[node_index])
    return hits


def _positive_zero(flow, parents, projection, acc, unions, pointer_parameters):
    def statement(index):
        node = flow.nodes[index]
        return flow.part.clean[node.start:node.end].strip()

    for index in _prior_references(flow, parents, projection, acc) or (None,):
        if index is None:
            return False
        assignment = re.fullmatch(rf'{acc}\s*=\s*(.+?)\s*;', statement(index))
        if not assignment:
            return False
        if re.fullmatch(r'0\.0[fF]', assignment[1]):
            continue
        member = re.fullmatch(rf'({IDENT})\s*\.\s*({IDENT})', assignment[1])
        union = unions.get(member[1]) if member else None
        if (not union or union['number'] != member[2] or _escaped(flow.part.body, union['name'])
                or not _in_scope(flow.part, union.start(), flow.nodes[index].start)):
            return False
        writes = _prior_references(flow, parents, index, union['name'])
        if not writes:
            return False
        zero = rf'(?:0[uU]?|\((?:u32|unsigned\s+int)\)\s*({IDENT})\s*&\s*~\((?:u32|unsigned\s+int)\)\s*\1)'
        assign = rf'{union["name"]}\s*\.\s*{union["bits"]}\s*=\s*{zero}\s*;'
        for write in writes:
            definition = re.fullmatch(assign, statement(write))
            if not definition or (definition[1] and definition[1] not in pointer_parameters):
                return False
    return True


def variants(source, name, rows, *, header=''):
    witness = _evidence(rows)
    visible = _visible(source, name, header) if witness else None
    if not visible:
        return []
    part, context = visible
    if re.search(r'\b(?:setjmp|longjmp|asm|__asm__)\b', part.body):
        return []
    if re.search(r'\btypedef\b[^;\n]*\b(?:volatile|_Atomic)\b[^;\n]*\b(?:f32|u32|s32)\s*;', context):
        return []
    prefix = part.clean[:part.opening]
    signature = re.search(rf'\b{re.escape(name)}\s*\(([^;{{}}]*)\)\s*$', prefix)
    macros = set(re.findall(rf'(?m)^[ \t]*#\s*(?:define|undef)\s+({IDENT})', context))
    pointer_parameters = {
        param[1] for arg in signature[1].split(',')
        if (param := re.fullmatch(rf'\s*(?:void|char)\s*\*\s*({IDENT})\s*', arg))
        and param[1] not in macros
        and not re.search(rf'\b(?:volatile|_Atomic)\b[^;{{}}]*\b{param[1]}\b', part.body)
    } if signature else set()
    floats = _typed_locals(part, r'(?:f32|float)')
    ints = _typed_locals(part, r'(?:s32|int)')
    declarations = [m for m in _DECL.finditer(part.clean, part.opening + 1, part.end)
                    if m['name'] in floats and m.start() == floats[m['name']][1]]
    unions = {m['name']: m for m in _ZERO_UNION.finditer(part.clean, part.opening + 1, part.end)}
    try:
        flow = Flow(part, declarations)
    except (ValueError, RecursionError):
        return []
    parents = [set() for _ in flow.nodes]
    for index, node in enumerate(flow.nodes):
        for child in node.successors:
            parents[child].add(index)
    indices = {node.start: i for i, node in enumerate(flow.nodes)}
    folded = fresh(source, header, 'repair_early_fold')
    proposals = []
    for guard in _PREDICATES.finditer(part.clean, part.opening + 1, part.end):
        first, second, axis = guard['first'], guard['second'], guard['value']
        if first == second or not all(flag in ints and _in_scope(part, ints[flag][1], guard.start())
                                      and not _escaped(part.body, flag) for flag in (first, second)):
            continue
        load = _LOAD.search(part.clean, max(part.opening + 1, guard.start() - 160), guard.start())
        field = _field(load['field'], prefix) if load and load['axis'] == axis else None
        if not field:
            continue
        try:
            bits = struct.unpack('>I', struct.pack('>f', float(guard['limit'][:-1])))[0]
        except OverflowError:
            continue
        gate = re.search(rf'\(\s*{second}\s*\^\s*1\s*\)\s*\|\s*{re.escape(guard["inverted"])}$',
                         part.clean[guard.start():guard.end('inverted')])
        position = ints[first][1]
        indent = source[source.rfind('\n', 0, position) + 1:position]
        if not gate or indent.strip():
            continue
        following = list(_PROJECTION.finditer(part.clean, guard.end(), min(guard.end() + 380, part.end)))
        for projection in reversed(following):
            acc = projection['acc']
            node = flow.at(projection.start('acc'))
            if (projection['axis'] != axis or axis == acc or not node or acc not in flow.names
                    or not _in_scope(part, floats[acc][1], projection.start('acc'))
                    or (bits, field[1], projection['call']) not in witness
                    or not macros_safe(source, header, part.body, {first, second, axis, acc, *unions})
                    or not _positive_zero(flow, parents, indices[node.start], acc, unions, pointer_parameters)):
                continue
            old_or = guard.start() + gate.start()
            old_second = gate[0].split('|', 1)[0].rstrip()
            proposals.append((FAMILY, edit(source, [
                (position, position, f'{ints[first][0]} {folded};\n{indent}'),
                (guard.start('pad'), guard.start('pad'), f'{guard["pad"]}{folded} = {first} ^ 1;\n'),
                (old_or, guard.end('inverted'), f'{folded} | {old_second}'),
                (*projection.span('initial'), '+='),
            ])))
            if len(proposals) == 4:
                return proposals
    return proposals
