"""Stage a float sample before reading the old smoothing field."""

import re
import struct

from .clamp_return_local import _field
from .integer_repair_support import IDENT, NUMBER, edit, integer
from .operand_lifetime_repairs import _escaped, _in_scope, _typed_locals, _visible

FAMILY = 'smoothing_call_before_read'
_FPR = r'\$f(?:[12]?[0-9]|3[01])'
_SAVED = r'\$f(?:20|22|24|26|28|30)'
_CALL = re.compile(rf'jal ({IDENT})')
_MUL = re.compile(rf'mul\.s ({_SAVED}), \$f0, ({_FPR})')
_LOAD = re.compile(rf'lwc1 ({_FPR}), ({NUMBER})(\(\$\w+\))')
_LUI = re.compile(rf'lui \$at, ({NUMBER})')
_ORI = re.compile(rf'ori \$at, \$at, ({NUMBER})')
_LITERAL = r'\d+\.\d+[fF]'
_ARG = rf'(?:{IDENT}|-?{NUMBER})'
_SOURCE = re.compile(
    rf'(?m)^(?P<pad>[ \t]*)(?P<old>{IDENT})\s*=\s*(?P<field>\*[^;={{}}\n]+?)\s*;\s*'
    rf'(?P<result>{IDENT})\s*=\s*\(\(\s*(?P<multiply>\(\s*(?P<expr>(?P<call>{IDENT})\(\s*'
    rf'(?:{_ARG}\s*(?:,\s*{_ARG}\s*)*)?\)\s*\*\s*(?P<scale>{_LITERAL}))\s*\))'
    rf'\s*-\s*(?P=old)\)\s*\*\s*{_LITERAL}\)\s*\+\s*(?P=old)\s*;\s*'
    rf'(?P=field)\s*=\s*(?P=result)\s*;\s*if\s*\(\s*(?P=result)\s*<\s*\(-{_LITERAL}\)\s*\)'
)


def _evidence(rows):
    target = [(i, left) for i, (_, left, _) in enumerate(rows) if left]
    witnesses = set()
    for j in range(6, len(target) - 2):
        _, op = target[j]
        mul = _MUL.fullmatch(op)
        load = _LOAD.fullmatch(target[j + 1][1])
        if not mul or not load or target[j + 2][1] != f'sub.s $f2, {mul[1]}, {load[1]}':
            continue
        before = [line for _, line in target[j - 6:j]]
        call = _CALL.fullmatch(before[0])
        upper = _LUI.fullmatch(before[2])
        lower = _ORI.fullmatch(before[3])
        if not call or not upper or not lower or before[4:] != [f'mtc1 $at, {mul[2]}', 'nop']:
            continue
        candidates = [right for _, _, right in rows[max(0, target[j - 6][0] - 1):target[j + 2][0] + 1] if right]
        call_at = next((i for i, line in enumerate(candidates) if line == before[0]), None)
        if call_at is None or any(
            match and match.groups()[1:] == load.groups()[1:]
            for match in map(_LOAD.fullmatch, candidates[call_at + 1:])
        ):
            continue
        if any(
            match and match.groups()[1:] == load.groups()[1:]
            for match in map(_LOAD.fullmatch, candidates[:call_at])
        ):
            witnesses.add((call[1], integer(load[2]), (integer(upper[1]) << 16) | integer(lower[1])))
    return witnesses


def variants(source, name, rows, *, header=''):
    witnesses = _evidence(rows)
    visible = _visible(source, name, header) if witnesses else None
    if not visible:
        return []
    part, context = visible
    if re.search(r'\btypedef\b[^;\n]*\b(?:volatile|_Atomic)\b[^;\n]*\bf32\s*;', context):
        return []
    available = _typed_locals(part, r'(?:f32|float)')
    macros = set(re.findall(rf'(?m)^[ \t]*#\s*(?:define|undef)\s+({IDENT})', context))
    proposals = []
    for m in _SOURCE.finditer(part.clean, part.opening + 1, part.end):
        result, old = m['result'], m['old']
        field = _field(m['field'], part.clean[:part.opening])
        if not field or result in (old, field[0]):
            continue
        if not re.search(rf'\b(?:f32|float)\s+{m["call"]}\s*\(', context):
            continue
        if any(local not in available or not _in_scope(part, available[local][1], m.start())
               or _escaped(part.body, local) for local in (result, old)):
            continue
        if any(re.search(rf'\b(?:volatile|_Atomic)\b[^;{{}}\n]*\b{local}\b', context)
               for local in (result, old, field[0])):
            continue
        if old in re.findall(IDENT, m['expr']) or macros & set(re.findall(IDENT, m[0])):
            continue
        if re.search(r'/[*/]|#', source[m.start():m.end()]):
            continue
        before = part.clean[part.opening + 1:m.start()].rstrip()
        if before and before[-1] not in ';{}:':
            continue
        try:
            bits = struct.unpack('>I', struct.pack('>f', float(m['scale'][:-1])))[0]
        except OverflowError:
            continue
        if (m['call'], field[1], bits) not in witnesses:
            continue
        expression = source[slice(*m.span('expr'))]
        intro = f'{m["pad"]}{result} = {expression};\n'
        proposals.append((FAMILY, edit(source, [(m.start(), m.start(), intro), (*m.span('multiply'), result)])))
        if len(proposals) == 4:
            break
    return proposals
