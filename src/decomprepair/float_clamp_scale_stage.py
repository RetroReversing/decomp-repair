"""Stage a float scale before a smoothing clamp."""

import re
import struct
from itertools import islice

from .clamp_return_local import _field
from .integer_repair_support import IDENT, NUMBER, edit, integer
from .operand_lifetime_repairs import _escaped, _in_scope, _typed_locals, _visible

FAMILY = 'float_clamp_scale_stage'
IN_PLACE = 'float_clamp_axis_stage'
SIGNED_SQUARE = 'float_clamp_signed_square'
_FPR = r'\$f(?:[12]?[0-9]|3[01])'
_SAVED = r'\$f(?:20|22|24|26|28|30)'
_LITERAL = r'\d+\.\d+[fF]'
_MUL = re.compile(rf'mul\.s ({_FPR}), ({_FPR}), ({_FPR})')
_LUI = re.compile(rf'lui \$at, ({NUMBER})')
_ORI = re.compile(rf'ori \$at, \$at, ({NUMBER})')
_MTC = re.compile(rf'mtc1 \$at, ({_FPR})')
_LOAD = re.compile(rf'lwc1 ({_FPR}), ({NUMBER})(\(\$\w+\))')
_FIELD = r'\*[^;={}\n]+?'
_BLEND = (
    rf'(?m)^(?P<pad>[ \t]*)(?P<old>{IDENT})\s*=\s*(?P<field>{_FIELD})\s*;\s*'
    rf'(?P<assignment>(?P<result>{IDENT})\s*=\s*\(\(\s*(?P<multiply>\(\s*(?P<axis>{IDENT})\s*\*\s*(?P<scale>{_LITERAL})\s*\))'
    rf'\s*-\s*(?P=old)\)\s*\*\s*{_LITERAL}\)\s*\+\s*(?P=old);)\s*'
    rf'(?P<store>{_FIELD})\s*=\s*(?P=result);\s*if\s*\(\s*(?P=result)\s*<\s*\(-(?P<bound>{_LITERAL})\)\s*\)\s*\{{'
)
_SOURCE = re.compile(_BLEND)
_CLAMP_TAIL = (
    rf'\s*(?P<lower>{_FIELD})\s*=\s*-(?P=bound)\s*;\s*\}}\s*else\s*'
    rf'if\s*\(\s*(?P=result)\s*>\s*(?P=bound)\s*\)\s*\{{\s*(?P<upper>{_FIELD})\s*=\s*(?P=bound)\s*;'
    r'\s*\}'
)
_RELOADED = re.compile(_BLEND + _CLAMP_TAIL + rf'\s*(?P=axis)\s*=\s*(?P<reload>{_FIELD})\s*;')
_SIGNED = re.compile(
    rf'(?m)^[ \t]*(?P<original>{IDENT})\s*=\s*(?P<before>{IDENT})\s*;\s*'
    rf'(?P=before)\s*=\s*(?P=before)\s*\*\s*(?P=before)\s*;\s*'
    rf'if\s*\(\s*(?P<check>(?P=original))\s*<\s*0\.0[fF]\s*\)\s*'
    rf'\{{\s*(?P=before)\s*=\s*-(?P=before)\s*;\s*\}}\s*\n'
)
_SAVED_SIGN = re.compile(
    rf'\s*\{{\s*(?:f32|float)\s+(?P<saved>{IDENT})\s*=\s*(?P<start>{IDENT})\s*;\s*'
    rf'(?P=start)\s*=\s*(?P<field>{_FIELD})\s*;\s*(?P<global>{IDENT})\s*-=\s*(?P=start)\s*;\s*'
    rf'(?P=start)\s*=\s*(?P=saved)\s*;\s*\}}\s*'
    rf'(?P=start)\s*=\s*{IDENT}\((?P<arguments>[^;{{}}\n]+)\)\s*;'
)
_RELOADED_CLAMP = re.compile(_BLEND + _CLAMP_TAIL)
_SIGN_COPY = re.compile(rf'mov\.s ({_SAVED}), ({_SAVED})')


def _witnesses(rows, *, signed=False):
    targets = [(i, marker, left) for i, (marker, left, _) in enumerate(rows) if left]
    witnesses = set()
    for current in range(3, len(targets) - 2):
        index, marker, op = targets[current]
        mul = _MUL.fullmatch(op)
        if not mul or marker == ' ' or mul[1] != mul[2] or not re.fullmatch(_SAVED, mul[1]):
            continue
        line = targets[current - 1][2]
        move = _MTC.fullmatch(targets[current - 2][2])
        partial = targets[current - 3][2]
        lower = _ORI.fullmatch(partial)
        upper = _LUI.fullmatch(targets[current - 4][2]) if lower and current >= 4 else _LUI.fullmatch(partial)
        if line != 'nop' or not move or move[1] != mul[3] or not upper:
            continue
        load = _LOAD.fullmatch(targets[current + 1][2])
        if not load or not re.fullmatch(rf'sub\.s {_FPR}, {re.escape(mul[1])}, {re.escape(load[1])}', targets[current + 2][2]):
            continue
        if signed and not _sign_copy(rows, targets, current, mul[1]):
            continue
        start, end = targets[current - 2][0], targets[current + 2][0]
        nearby = [right for _, _, right in rows[start:end + 1] if right]
        for first, second, third in zip(nearby, nearby[1:], nearby[2:]):
            other_mul, other_load = _MUL.fullmatch(first), _LOAD.fullmatch(second)
            if (other_mul and other_mul[1] != other_mul[2] and other_mul[3] == mul[3]
                    and other_load and other_load.groups()[1:] == load.groups()[1:]
                    and re.fullmatch(rf'sub\.s {_FPR}, {re.escape(other_mul[1])}, {re.escape(other_load[1])}', third)):
                witnesses.add((integer(load[2]), (integer(upper[1]) << 16) | (integer(lower[1]) if lower else 0)))
    return witnesses


def _sign_copy(rows, targets, current, axis):
    for i in range(max(2, current - 14), current - 4):
        index, _, op = targets[i]
        copy = _SIGN_COPY.fullmatch(op)
        if not copy or copy[2] != axis or copy[1] == axis:
            continue
        zero = re.fullmatch(rf'mtc1 \$zero, ({_FPR})', targets[i - 1][2])
        candidate_zero = re.fullmatch(rf'mtc1 \$zero, ({_FPR})', rows[targets[i - 1][0]][2])
        compare, _, comparison = targets[i + 1]
        if (zero and candidate_zero and comparison == f'c.lt.s {copy[1]}, {zero[1]}'
                and rows[index][2] == 'nop' and rows[compare][2] == f'c.lt.s $f0, {candidate_zero[1]}'
                and targets[i + 5][2] == f'mul.s {axis}, {axis}, {axis}'
                and targets[i + 6][2] == f'neg.s {axis}, {axis}'):
            return True
    return False


def _signed_square(source, part, context, macros, types, prefix, witness):
    clamps = {m.start(): m for m in _RELOADED_CLAMP.finditer(part.clean, part.opening + 1, part.end)}
    direct = {m.start(): m for m in _RELOADED.finditer(part.clean, part.opening + 1, part.end)}
    for square in _SIGNED.finditer(part.clean, part.opening + 1, part.end):
        clamp = clamps.get(square.end())
        axis, original = square['before'], square['original']
        if not clamp or clamp['axis'] != axis:
            continue
        result, scale = clamp['result'], clamp['scale']
        locals_used = (axis, original, clamp['old'], result)
        if len(set(locals_used)) != 4 or any(
            local not in types or not _in_scope(part, types[local][1], square.start())
            or _escaped(part.body, local) for local in locals_used
        ):
            continue
        if len(re.findall(rf'\b{original}\b', part.body)) != 3:
            continue
        if any(re.search(rf'\b(?:volatile|_Atomic)\b[^;{{}}\n]*\b{local}\b', context) for local in locals_used):
            continue
        field = _field(clamp['field'], prefix)
        if not field or field[0] in locals_used or any(
            _field(clamp[key], prefix) != field for key in ('store', 'lower', 'upper')
        ):
            continue
        try:
            bits = struct.unpack('>I', struct.pack('>f', float(scale[:-1])))[0]
        except OverflowError:
            continue
        if (field[1], bits) not in witness:
            continue
        reload = direct.get(clamp.start())
        restored = _SAVED_SIGN.match(part.clean, clamp.end(), part.end)
        if not (reload and _field(reload['reload'], prefix) == field):
            # The old axis may be restored briefly if it is overwritten before the next use.
            if (not restored or restored['start'] != axis or _field(restored['field'], prefix) != field
                    or restored['saved'] in (*locals_used, restored['global'])
                    or restored['global'] in locals_used or axis in re.findall(IDENT, restored['arguments'])):
                continue
            reload = restored
        snippet = source[square.start():reload.end()]
        if re.search(r'/[*/]|#', snippet) or macros & set(re.findall(IDENT, snippet)):
            continue
        prior = part.clean[part.opening + 1:square.start()].rstrip()
        if prior and prior[-1] not in ';{}:':
            continue
        yield SIGNED_SQUARE, edit(source, [
            (*square.span('original'), result),
            (*square.span('check'), result),
            (clamp.start(), clamp.start(), f'{clamp["pad"]}{axis} *= {scale};\n'),
            (*clamp.span('multiply'), axis),
        ])


def variants(source, name, rows, *, header=''):
    witness = _witnesses(rows)
    visible = _visible(source, name, header) if witness else None
    if not visible:
        return []
    part, context = visible
    if re.search(r'\btypedef\b[^;\n]*\b(?:volatile|_Atomic)\b[^;\n]*\bf32\s*;', context):
        return []
    types = _typed_locals(part, r'(?:f32|float)')
    macros = set(re.findall(rf'(?m)^[ \t]*#\s*(?:define|undef)\s+({IDENT})', context))
    prefix = part.clean[:part.opening]
    signed = _witnesses(rows, signed=True)
    proposals = list(islice(_signed_square(source, part, context, macros, types, prefix, signed), 4)) if signed else []
    if len(proposals) == 4:
        return proposals
    reloaded = {hit.start(): hit for hit in _RELOADED.finditer(part.clean, part.opening + 1, part.end)}
    for m in _SOURCE.finditer(part.clean, part.opening + 1, part.end):
        axis, result, scale = m['axis'], m['result'], m['scale']
        locals_used = (axis, result, m['old'])
        if len(set(locals_used)) != 3 or any(
            local not in types or not _in_scope(part, types[local][1], m.start())
            or _escaped(part.body, local) for local in locals_used
        ):
            continue
        if any(re.search(rf'\b(?:volatile|_Atomic)\b[^;{{}}\n]*\b{local}\b', context) for local in locals_used):
            continue
        try:
            bits = struct.unpack('>I', struct.pack('>f', float(scale[:-1])))[0]
        except OverflowError:
            continue
        field = _field(m['field'], prefix)
        if (not field or field[0] in locals_used or field != _field(m['store'], prefix)
                or (field[1], bits) not in witness):
            continue
        if re.search(r'/[*/]|#', source[m.start():m.end()]) or macros & set(re.findall(IDENT, m[0])):
            continue
        prior = part.clean[part.opening + 1:m.start()].rstrip()
        if prior and prior[-1] not in ';{}:':
            continue
        joined = reloaded.get(m.start())
        if (joined and all(_field(joined[key], prefix) == field for key in ('lower', 'upper', 'reload'))
                and not re.search(r'/[*/]|#', source[joined.start():joined.end()])
                and not macros & set(re.findall(IDENT, joined[0]))):
            change = f'{m["pad"]}{axis} = {axis} * {scale};\n'
            proposals.append((IN_PLACE, edit(source, [(m.start(), m.start(), change),
                                                        (*m.span('multiply'), axis)])))
        assignment = m.start('assignment')
        replacement = f'{result} = {axis} * {scale};\n{m["pad"]}'
        proposals.append((FAMILY, edit(source, [(assignment, assignment, replacement),
                                                (*m.span('multiply'), result)])))
        if len(proposals) >= 4:
            break
    return proposals[:4]
