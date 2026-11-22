"""Pair an earlier integer predicate stage with a later saved float return."""

import re
import struct

from .clamp_return_local import _field
from .compiler_phase_repairs import fresh
from .integer_repair_support import IDENT, NUMBER, edit, integer, refs
from .local_flow import Flow
from .operand_lifetime_repairs import _in_scope, _typed_locals, _visible

FAMILY = 'balanced_float_predicate_return'
_SAVED = r'\$f(?:20|22|24|26|28|30)'
_FPR = r'\$f(?:[12]?[0-9]|3[01])'
_LUI = re.compile(rf'lui \$at, ({NUMBER})')
_ORI = re.compile(rf'ori \$at, \$at, ({NUMBER})')
_SAVED_COMPARE = re.compile(rf'c\.le\.s ({_SAVED}), ({_FPR})')
_RESULT = re.compile(rf'mov\.s ({_SAVED}), \$f0')
_FIELD_LOAD = re.compile(rf'lwc1 ({_FPR}), ({NUMBER})(\(\$\w+\))')
_CALL = re.compile(rf'jal ({IDENT})')
_PLAIN_FLOAT = re.compile(rf'\b(?P<type>f32|float)\s+(?P<name>{IDENT})\s*;')
_LITERAL = r'\d+\.\d+[fF]'
_PREDICATES = re.compile(
    rf'(?m)^[ \t]*(?P<first>{IDENT})\s*=\s*1\s*;\s*'
    rf'if\s*\(!\((?P<value>{IDENT})\s*<=\s*(?P<limit>{_LITERAL})\)\)\s*'
    rf'\{{\s*(?P=first)\s*=\s*(?:\(unsigned\s+int\)\s*)?0\s*;\s*\}}\s*'
    rf'^(?P<pad>[ \t]*)(?P<second>{IDENT})\s*=\s*1\s*;\s*'
    rf'if\s*\(!\((?P=value)\s*>=\s*\(-(?P=limit)\)\)\)\s*'
    rf'\{{\s*(?P=second)\s*=\s*0\s*;\s*\}}\s*'
    r'if\s*\(\(\(\s*(?P=second)\s*\^\s*1\)\s*\|\s*(?P<inverted>\(\s*(?P=first)\s*\^\s*1\))'
    r'\s*\)\s*[!=]=\s*0\s*\)'
)
_RETURN = re.compile(
    rf'(?m)^[ \t]*(?P<result>{IDENT})\s*=\s*(?P<call>{IDENT})\([^;{{}}\n]+\)\s*;\s*'
    rf'(?P<field>\*[^;={{}}\n]+?)\s*=\s*\(f32\)\s*\(\((?P=field)\)\s*\+\s*(?P=result)\);\s*'
    rf'if\s*\(\s*(?P=result)\s*==\s*0\.0[fF]\s*\)'
)


def _bits(target, index, register):
    if index < 4 or target[index - 2][1] != f'mtc1 $at, {register}' or target[index - 1][1] != 'nop':
        return None
    upper, lower = _LUI.fullmatch(target[index - 4][1]), _ORI.fullmatch(target[index - 3][1])
    return (integer(upper[1]) << 16) | integer(lower[1]) if upper and lower else None


def _earlier(rows, target, *, same_comparisons=True):
    for i, (start, op) in enumerate(target):
        match = _SAVED_COMPARE.fullmatch(op)
        if not match:
            continue
        value, bound = match.groups()
        bits = _bits(target, i, bound)
        if not bits or bits & 0x80000000:
            continue
        for j in range(i + 5, min(i + 13, len(target) - 7)):
            index, op = target[j]
            reverse = re.fullmatch(rf'c\.le\.s ({_FPR}), {re.escape(value)}', op)
            if not reverse or (same_comparisons and reverse[1] != bound):
                continue
            if _bits(target, j, reverse[1]) != bits | 0x80000000:
                continue
            following = [op for _, op in target[j + 1:j + 8]]
            if (following[:2] != ['addiu $v0, $zero, 1', 'nop'] or not following[2].startswith('bc1t ')
                    or following[3:] != ['xori $v1, $v1, 1', 'move $v0, $zero', 'xori $v0, $v0, 1', 'or $v0, $v1, $v0']):
                continue
            other = [right for _, _, right in rows[index:target[j + 7][0] + 1] if right]
            if same_comparisons:
                agrees = rows[start][2] == match[0] and rows[index][2] == op
            else:
                candidate = _SAVED_COMPARE.fullmatch(rows[start][2])
                agrees = candidate and re.fullmatch(rf'c\.le\.s {_FPR}, {re.escape(candidate[1])}', rows[index][2])
            if (agrees and other[1:3] == ['nop', 'nop'] and len(other) > 4
                    and other[3].startswith('bc1t ') and other[4] == 'addiu $v0, $zero, 1'):
                yield index, value, bits


def _later(rows, target):
    for i in range(2, len(target) - 4):
        index, op = target[i]
        move = _RESULT.fullmatch(op)
        load = _FIELD_LOAD.fullmatch(target[i - 1][1])
        if not move or not load or rows[index][0] == ' ':
            continue
        register = load[1]
        if target[i + 1][1] != f'add.s {register}, {register}, {move[1]}':
            continue
        end = target[min(i + 8, len(target) - 1)][0]
        following = {op for _, op in target[i + 2:i + 9]}
        if not {f'c.eq.s {move[1]}, $f0', f'swc1 {register}, {load[2]}{load[3]}'} <= following:
            continue
        before = [op for _, op in target[max(0, i - 6):i - 1]]
        call = next((m[1] for op in reversed(before) if (m := _CALL.fullmatch(op))), None)
        neighbors = [right for _, _, right in rows[target[i - 1][0]:end + 1] if right]
        if call and any(re.fullmatch(rf'add\.s ({_FPR}), \1, \$f0', op) for op in neighbors):
            yield index, move[1], call, integer(load[2])


def _evidence(rows):
    target = [(i, left) for i, (_, left, _) in enumerate(rows) if left]
    earlier, later = list(_earlier(rows, target)), list(_later(rows, target))
    # Require the same saved float register at both ends before pairing the source edits.
    return {(bits, call, offset) for begin, axis_register, bits in earlier
            for end, return_register, call, offset in later if begin < end and axis_register == return_register}


def _can_reuse(flow, declarations, m, old, new):
    part = flow.part
    return (old in flow.names and new in flow.names and old != new
            and _in_scope(part, declarations[new].start(), m.start())
            and flow.dead(new, m.start('result'))
            and len(refs(part, declarations[old])) == 3
            and sum(1 for node in flow.nodes if old in node.defines and node.start >= declarations[old].end()) == 1)


def variants(source, name, rows, *, header=''):
    witness = _evidence(rows)
    visible = _visible(source, name, header) if witness else None
    if not visible:
        return []
    part, context = visible
    if re.search(r'\btypedef\b[^;\n]*\b(?:volatile|_Atomic)\b[^;\n]*\bf32\s*;', context):
        return []
    macros = set(re.findall(rf'(?m)^[ \t]*#\s*(?:define|undef)\s+({IDENT})', context))
    floats = _typed_locals(part, r'(?:f32|float)')
    ints = _typed_locals(part, r'(?:s32|int)')
    declarations = {m['name']: m for m in _PLAIN_FLOAT.finditer(part.clean, part.opening + 1, part.end)
                    if m['name'] in floats and m.start() == floats[m['name']][1]}
    try:
        flow = Flow(part, declarations.values())
    except (ValueError, RecursionError):
        return []
    new_flag = fresh(source, header, 'repair_first_inverted')
    proposals = []
    early = list(_PREDICATES.finditer(part.clean, part.opening + 1, part.end))
    for m in _RETURN.finditer(part.clean, part.opening + 1, part.end):
        field = _field(m['field'], part.clean[:part.opening])
        if not field or macros & set(re.findall(IDENT, m[0])):
            continue
        old = m['result']
        for guard in early:
            axis, first, second = guard['value'], guard['first'], guard['second']
            if guard.end() >= m.start() or not _can_reuse(flow, declarations, m, old, axis):
                continue
            if first not in ints or second not in ints or first == second:
                continue
            if not all(_in_scope(part, ints[flag][1], guard.start()) for flag in (first, second)):
                continue
            if macros & set(re.findall(IDENT, guard[0])) or axis in set(re.findall(IDENT, m[0])):
                continue
            try:
                bits = struct.unpack('>I', struct.pack('>f', float(guard['limit'][:-1])))[0]
            except OverflowError:
                continue
            if (bits, m['call'], field[1]) not in witness:
                continue
            if any(re.search(rf'\b(?:volatile|_Atomic)\b[^;{{}}\n]*\b{local}\b', context)
                   for local in (axis, old, first, second)):
                continue
            position = ints[first][1]
            line = source.rfind('\n', 0, position) + 1
            indent = source[line:position]
            if indent.strip():
                continue
            edits = [(position, position, f'{ints[first][0]} {new_flag};\n{indent}'),
                     (guard.start('pad'), guard.start('pad'), f'{guard["pad"]}{new_flag} = {first} ^ 1;\n'),
                     (*guard.span('inverted'), new_flag)]
            edits += [(use.start(), use.end(), axis) for use in refs(part, declarations[old])]
            proposals.append((FAMILY, edit(source, edits)))
            if len(proposals) == 4:
                return proposals
    return proposals
