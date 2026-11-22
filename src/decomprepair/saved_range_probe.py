"""Reuse a completed saved float lifetime for a later two-bound probe."""

import re

from .clamp_return_local import _field
from .integer_repair_support import IDENT, NUMBER, edit, integer
from .operand_lifetime_repairs import _escaped, _in_scope, _typed_locals, _visible

FAMILY = 'saved_float_range_probe'
_SAVED = r'\$f(?:20|22|24|26|28|30)'
_LOAD = re.compile(rf'lwc1 ({_SAVED}), ({NUMBER})(\(\$\w+\))')
_CALL = re.compile(rf'jal ({IDENT})')
_MOVE = re.compile(rf'mov\.s ({_SAVED}), \$f0')
_CANDIDATE_MOVE = re.compile(r'mov\.s (\$f(?:[02468]|1[02468])), \$f0')
_RESTORE = re.compile(
    rf'(?m)^\s*(?P<save>{IDENT})\s*=\s*(?P<read>\*[^;={{}}\n]+?)\s*;\s*'
    rf'(?:{IDENT}\s*=\s*(?:-?\d+\.\d+[fF]|\d+)\s*;\s*){{0,2}}'
    rf'(?P<callee>{IDENT})\([^;{{}}\n]*\)\s*;\s*(?P<write>\*[^;={{}}\n]+?)\s*=\s*(?P=save)\s*;'
)
_PROBE = re.compile(
    rf'(?m)^\s*(?P<probe>{IDENT})\s*=\s*(?P<callee>{IDENT})\([^;{{}}\n]+\)\s*;\s*'
    rf'(?P<upper>{IDENT})\s*=\s*1\s*;\s*if\s*\(!\((?P=probe)\s*<=\s*(?P<bound>\d+\.\d+[fF])\)\)'
    rf'\s*\{{\s*(?P=upper)\s*=\s*0\s*;\s*\}}\s*'
    rf'(?P<lower>{IDENT})\s*=\s*1\s*;\s*if\s*\(!\((?P=probe)\s*>=\s*\(-(?P=bound)\)\)\)'
    rf'\s*\{{\s*(?P=lower)\s*=\s*0\s*;\s*\}}'
)


def _evidence(rows):
    targets = [(i, left, right) for i, (_, left, right) in enumerate(rows) if left]
    restores, probes = [], []
    for j, (index, line, right) in enumerate(targets):
        load = _LOAD.fullmatch(line)
        if load and line == right:
            store = f'swc1 {load[1]}, {load[2]}{load[3]}'
            calls = []
            for _, left, current in targets[j + 1:j + 8]:
                if call := _CALL.fullmatch(left):
                    calls.append(call[1])
                if left == current == store and len(calls) == 1:
                    restores.append((index, calls[0], integer(load[2]), load[1]))
                    break
        move = _MOVE.fullmatch(line)
        other = _CANDIDATE_MOVE.fullmatch(right)
        if not move or not other or j + 1 == len(targets):
            continue
        _, left_cmp, right_cmp = targets[j + 1]
        if not (left_cmp.startswith(f'c.le.s {move[1]}, ')
                and right_cmp == left_cmp.replace(move[1], other[1], 1)):
            continue
        before = targets[max(0, j - 8):j]
        call = next((m[1] for _, op, _ in reversed(before) if (m := _CALL.fullmatch(op))), None)
        if call and any(
            left_cmp == f'c.le.s $f0, {move[1]}' and right_cmp == f'c.le.s $f0, {other[1]}'
            for _, left_cmp, right_cmp in targets[j + 2:j + 16]
        ):
            probes.append((index, call, move[1]))
    return {
        (before_call, offset, after_call)
        for start, before_call, offset, saved in restores
        for end, after_call, register in probes
        if start < end and saved == register
    }


def _ordinary(part, context, local, declarations, extent, count):
    if (local not in declarations or not _in_scope(part, declarations[local][1], extent.start())
            or _escaped(part.body, local)
            or re.search(rf'\b(?:volatile|_Atomic)\b[^;{{}}\n]*\b{local}\b', context)):
        return False
    references = [
        part.opening + 1 + match.start() for match in re.finditer(rf'\b{local}\b', part.body)
    ]
    return (len(references) == count + 1 and references[0] >= declarations[local][1]
            and references[0] < extent.start() and all(extent.start() <= pos < extent.end() for pos in references[1:]))


def variants(source, name, rows, *, header=''):
    pairs = _evidence(rows)
    visible = _visible(source, name, header) if pairs else None
    if not visible:
        return []
    part, context = visible
    if re.search(r'\btypedef\b[^;\n]*\b(?:volatile|_Atomic)\b[^;\n]*\bf32\s*;', context):
        return []
    declarations = _typed_locals(part, r'(?:f32|float)')
    macros = set(re.findall(rf'(?m)^[ \t]*#\s*(?:define|undef)\s+({IDENT})', context))
    restores = []
    for m in _RESTORE.finditer(part.clean, part.opening + 1, part.end):
        local = m['save']
        if macros & set(re.findall(IDENT, m[0])) or not _ordinary(part, context, local, declarations, m, 2):
            continue
        field = _field(m['read'], part.clean[:part.opening])
        if field and field == _field(m['write'], part.clean[:part.opening]):
            restores.append((m, field[1]))
    result = []
    for m in _PROBE.finditer(part.clean, part.opening + 1, part.end):
        local = m['probe']
        prefix = part.clean[part.opening + 1:m.start()].rstrip()
        if prefix and prefix[-1] not in ';{}:':
            continue
        if macros & set(re.findall(IDENT, m[0])) or not _ordinary(part, context, local, declarations, m, 3):
            continue
        for before, offset in restores:
            reuse = before['save']
            if (before.end() >= m.start() or (before['callee'], offset, m['callee']) not in pairs
                    or not _in_scope(part, declarations[reuse][1], m.start())):
                continue
            edits = [
                (m.start() + use.start(), m.start() + use.end(), reuse)
                for use in re.finditer(rf'\b{local}\b', m[0])
            ]
            result.append((FAMILY, edit(source, edits)))
            if len(result) == 4:
                return result
    return result
