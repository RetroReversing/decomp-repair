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
SUBTRACT = 'carried_zero_global_subtract'
SECOND = 'carried_zero_second_projection'
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
_MATCHED_PROJECTION = re.compile(
    rf'(?m)^[ \t]*(?P<acc>{IDENT})\s*\+=\s*\(\s*(?P<axis>{IDENT})\s*\*\s*'
    rf'(?P<call>{IDENT})\([^;{{}}\n]+\)\s*\)\s*;'
)
_PRODUCT = re.compile(rf'mul\.s \$f0, ({_FPR}), \$f0')
_IMMEDIATE_ZERO = re.compile(rf'mtc1 \$zero, ({_FPR})')

_ZERO_UNION = re.compile(
    rf'\bunion\s*\{{\s*(?:u32|unsigned\s+int)\s+(?P<bits>{IDENT})\s*;\s*'
    rf'(?:f32|float)\s+(?P<number>{IDENT})\s*;\s*\}}\s*(?P<name>{IDENT})\s*;'
)

_SUBTRACTION = re.compile(
    rf'(?m)^[ \t]*(?P<acc>{IDENT})\s*(?P<initial>=\s*(?P<zero>0\.0[fF]|{IDENT}\s*\.\s*{IDENT})\s*-\s*)'
    rf'(?P<symbol>{IDENT})\s*;'
)
_GLOBAL = re.compile(rf'lwc1 ({_FPR}), %lo\(({IDENT})\)\(\$at\)')


def _subtraction_evidence(rows):
    target = [(i, left) for i, (_, left, _) in enumerate(rows) if left]
    witnesses = set()
    for i in range(1, len(target) - 3):
        position, op = target[i]
        carry, candidate = _CARRY.fullmatch(op), _CARRY.fullmatch(rows[position][2])
        if not carry or not candidate or carry[1] == candidate[1] or carry[2] != candidate[2]:
            continue
        earlier = target[max(0, i - 4):i]
        load = next((m for row, line in reversed(earlier) if line == rows[row][2]
                     and (m := _GLOBAL.fullmatch(line))), None)
        if not load:
            continue
        gpr, register = carry.groups()
        scratch = load[1]
        if (register == scratch or [line for _, line in target[i + 1:i + 4]] !=
                ['nop', f'sub.s {register}, {register}, {scratch}', f'mfc1 {gpr}, {register}']):
            continue
        right = [rows[row][2] for row, _ in target[i + 1:i + 4]]
        if right == ['nop', f'sub.s {scratch}, {register}, {scratch}', f'mfc1 {gpr}, {scratch}']:
            witnesses.add(load[2])
    return witnesses


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



def _projection_transfers(rows):
    for at, (_, op, other) in enumerate(rows):
        call = _CALL.fullmatch(op)
        if not call or op != other:
            continue
        for offset, (_, left, right) in enumerate(rows[at + 1:at + 4], at + 1):
            product = _PRODUCT.fullmatch(left)
            if not product or left != right:
                continue
            after = rows[offset + 1:offset + 6]
            tail = after[:4]
            if (len(after) == 5 and after[3][1] == after[3][2]
                    and (load := _FIELD.fullmatch(after[3][1])) and load[1] == '$f12'):
                tail = [*after[:3], after[4]]
            if len(tail) != 4 or not (carry := _CARRY.fullmatch(tail[0][1])):
                break
            gpr, register = carry.groups()
            expected = [carry[0], 'nop', f'add.s {register}, {register}, $f0', f'mfc1 {gpr}, {register}']
            if [line for _, line, _ in tail] != expected:
                break
            actual = [line for _, _, line in tail]
            if actual == expected:
                yield at, call[1], product[1], gpr, False
            elif (zero := _IMMEDIATE_ZERO.fullmatch(actual[0])) and actual[1:] == [
                    'nop', f'add.s $f0, $f0, {zero[1]}', f'mfc1 {gpr}, $f0']:
                yield at, call[1], product[1], gpr, True
            break


def _adjacent_evidence(rows):
    transfers = list(_projection_transfers(rows))
    return {(first[1], second[1]) for first, second in zip(transfers, transfers[1:])
            if second[4] and not first[4] and first[1] != second[1] and first[2] == second[2]
            and first[3] != second[3] and second[0] - first[0] <= 12}


def _second_projections(part, witness):
    prior = list(_MATCHED_PROJECTION.finditer(part.clean, part.opening + 1, part.end))
    for projection in _PROJECTION.finditer(part.clean, part.opening + 1, part.end):
        before = next((m for m in reversed(prior) if m.end() <= projection.start()), None)
        if (before is not None and (before['call'], projection['call']) in witness
                and before['axis'] == projection['axis'] and before['acc'] != projection['acc']
                and not part.clean[before.end():projection.start()].strip()):
            yield before, projection


def _prior_references(flow, parents, index, name, ignore=None):
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
        statement = flow.part.clean[node.start:node.end].strip()
        if reference.search(statement) and not (ignore and ignore.fullmatch(statement)):
            hits.add(node_index)
        else:
            if node_index == flow.entry or not parents[node_index]:
                return None
            pending.extend(parents[node_index])
    return hits


def _statement(flow, index):
    node = flow.nodes[index]
    return flow.part.clean[node.start:node.end].strip()


def _known_zero(flow, parents, index, expression, unions, pointer_parameters):
    if re.fullmatch(r'0\.0[fF]', expression):
        return True
    member = re.fullmatch(rf'({IDENT})\s*\.\s*({IDENT})', expression)
    union = unions.get(member[1]) if member else None
    if (not union or union['number'] != member[2] or _escaped(flow.part.body, union['name'])
            or not _in_scope(flow.part, union.start(), flow.nodes[index].start)):
        return False
    read = re.compile(rf'{IDENT}\s*=\s*{union["name"]}\s*\.\s*{union["number"]}\s*;')
    writes = _prior_references(flow, parents, index, union['name'], ignore=read)
    if not writes:
        return False
    zero = rf'(?:0[uU]?|\((?:u32|unsigned\s+int)\)\s*({IDENT})\s*&\s*~\((?:u32|unsigned\s+int)\)\s*\1)'
    assign = rf'{union["name"]}\s*\.\s*{union["bits"]}\s*=\s*{zero}\s*;'
    for write in writes:
        definition = re.fullmatch(assign, _statement(flow, write))
        if not definition or (definition[1] and definition[1] not in pointer_parameters):
            return False
    return True


def _positive_zero(flow, parents, projection, acc, unions, pointer_parameters):
    refs = _prior_references(flow, parents, projection, acc)
    if not refs:
        return False
    for index in refs:
        assignment = re.fullmatch(rf'{acc}\s*=\s*(.+?)\s*;', _statement(flow, index))
        if not assignment or not _known_zero(flow, parents, index, assignment[1], unions, pointer_parameters):
            return False
    return True


def variants(source, name, rows, *, header=''):
    witness = _evidence(rows)
    subtract_globals = _subtraction_evidence(rows)
    adjacent = _adjacent_evidence(rows)
    visible = _visible(source, name, header) if witness or subtract_globals or adjacent else None
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
    for first, projection in _second_projections(part, adjacent):
        acc, axis = projection['acc'], projection['axis']
        node = flow.at(projection.start('acc'))
        if (acc not in flow.names or axis == acc or axis not in floats or not node
                or not _in_scope(part, floats[acc][1], projection.start('acc'))
                or re.search(rf'\b{acc}\b', part.clean[projection.end('initial'):projection.end()])
                or not macros_safe(source, header, part.body, {acc, axis, first['call'], projection['call'], *unions})
                or not _positive_zero(flow, parents, indices[node.start], acc, unions, pointer_parameters)):
            continue
        proposals.append((SECOND, edit(source, [(*projection.span('initial'), '+=')])))
        if len(proposals) == 4:
            return proposals
    for subtraction in _SUBTRACTION.finditer(part.clean, part.opening + 1, part.end):
        acc, symbol = subtraction['acc'], subtraction['symbol']
        node = flow.at(subtraction.start('acc'))
        if (symbol not in subtract_globals or not node or acc not in flow.names
                or not _in_scope(part, floats[acc][1], subtraction.start('acc'))
                or not macros_safe(source, header, part.body, {acc, symbol, *unions})):
            continue
        if not re.search(rf'\bextern\s+(?:f32|float)\s+{symbol}\s*;', context):
            continue
        index = indices[node.start]
        if (_positive_zero(flow, parents, index, acc, unions, pointer_parameters)
                and _known_zero(flow, parents, index, subtraction['zero'], unions, pointer_parameters)):
            proposals.append((SUBTRACT, edit(source, [(*subtraction.span('initial'), '-= ')])))
            if len(proposals) == 4:
                break
    return proposals
