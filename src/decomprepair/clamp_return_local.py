"""Reuse an ordinary float local for a clamp probe's return and following reload."""

import re
import struct

from .integer_repair_support import IDENT, NUMBER, edit, integer
from .operand_lifetime_repairs import _escaped, _in_scope, _typed_locals, _visible

FAMILY = 'clamp_return_local_reuse'
LIMIT = 4
REG = r'\$\w+'
_LITERAL = r'\d+\.\d+[fF]'
_LOAD = re.compile(rf'lwc1 \$f0, ({NUMBER})\(({REG})\)')
_CALL = re.compile(rf'jal ({IDENT})')
_HI = re.compile(rf'lui \$at, ({NUMBER})')
_LO = re.compile(rf'ori \$at, \$at, ({NUMBER})')
_FIELD = re.compile(rf'\*\(\(f32\*\)\(\(\(char\*\)({IDENT})\)\+({NUMBER})\)\)')
_HELPER = re.compile(rf'\*({IDENT})\(({IDENT})\)')
_SOURCE = re.compile(
    rf'(?m)^(?P<pad>[ \t]*)if\s*\(\s*\(\s*{IDENT}\s*&\s*{IDENT}\s*\)\s*&&\s*'
    rf'\(\s*(?P<call>(?P<callee>{IDENT})\(\s*{IDENT}\s*\))\s*<\s*{_LITERAL}\s*\)\s*\)\s*\{{\s*'
    rf'(?P<write>\*[^;={{}}\n]+?)\s*=\s*0\.0[fF]\s*;\s*\}}\s*'
    rf'(?P<local>{IDENT})\s*=\s*(?P<read>\*[^;{{}}\n]+?)\s*;\s*'
    rf'{IDENT}\s*=\s*-(?P<bound>{_LITERAL})\s*;'
)


def _witnesses(rows):
    targets = [(index, flag, left) for index, (flag, left, _) in enumerate(rows) if left]
    witnesses = set()
    for i in range(2, len(targets) - 5):
        index, mark, line = targets[i]
        load = _LOAD.fullmatch(line)
        if not load or mark == ' ' or targets[i - 1][2] != f'sw $zero, {load[1]}({load[2]})':
            continue
        if not targets[i - 2][2].startswith('bc1tl '):
            continue
        hi, lo, move, delay, compare = [row[2] for row in targets[i + 1:i + 6]]
        upper, lower = _HI.fullmatch(hi), _LO.fullmatch(lo)
        if not upper or not lower or (move, delay, compare) != ('mtc1 $at, $f2', 'nop', 'c.lt.s $f0, $f2'):
            continue
        prior = {right for _, _, right in rows[index:targets[i + 5][0] + 1]}
        if not {f'lwc1 $f2, {load[1]}({load[2]})', 'mtc1 $at, $f0', 'c.lt.s $f2, $f0'} <= prior:
            continue
        before = [op for _, _, op in targets[max(0, i - 14):i - 2]]
        caller = next((m[1] for op in reversed(before) if (m := _CALL.fullmatch(op))), None)
        if caller and 'c.lt.s $f0, $f2' in before:
            witnesses.add((caller, integer(load[1]), (integer(upper[1]) << 16) | integer(lower[1])))
    return witnesses


def _field(expression, prefix):
    compact = re.sub(r'\s+', '', expression)
    if field := _FIELD.fullmatch(compact):
        return field[1], integer(field[2])
    if not (call := _HELPER.fullmatch(compact)):
        return None
    helper = re.compile(
        rf'\b(?:inline\s+static|static\s+inline)\s+f32\s*\*\s*{call[1]}\(\s*void\s*\*\s*(?P<arg>{IDENT})\s*\)'
        rf'\s*\{{\s*return\s+\(f32\s*\*\)\s*\(\(\(char\s*\*\)\s*(?P=arg)\)\s*\+\s*({NUMBER})\)\s*;\s*\}}'
    )
    definitions = list(helper.finditer(prefix))
    return (call[2], integer(definitions[0][2])) if len(definitions) == 1 else None


def variants(source, name, rows, *, header=''):
    witness = _witnesses(rows)
    visible = _visible(source, name, header) if witness else None
    if not visible:
        return []
    part, context = visible
    if re.search(r'\btypedef\b[^;\n]*\bvolatile\b[^;\n]*\bf32\s*;', context):
        return []
    floats = _typed_locals(part, r'(?:f32|float)')
    macros = set(re.findall(rf'(?m)^[ \t]*#\s*(?:define|undef)\s+({IDENT})', context))
    sites = []
    for m in _SOURCE.finditer(part.clean, part.opening + 1, part.end):
        local, callee = m['local'], m['callee']
        if (local not in floats or not _in_scope(part, floats[local][1], m.start())
                or _escaped(part.body, local) or not re.search(rf'\bf32\s+{callee}\(\s*f32\s*\)', context)):
            continue
        field = _field(m['read'], part.clean[:part.opening])
        if not field or field[0] == local or field != _field(m['write'], part.clean[:part.opening]):
            continue
        try:
            bits = struct.unpack('>I', struct.pack('>f', -float(m['bound'][:-1])))[0]
        except OverflowError:
            continue
        if (callee, field[1], bits) not in witness:
            continue
        start = part.clean[part.opening + 1:m.start()].rstrip()
        if start and start[-1] not in ';{}:':
            continue
        text = source[m.start():m.end()]
        if re.search(r'/[*/]|#', text) or macros & set(re.findall(IDENT, text)):
            continue
        if re.search(rf'\b(?:volatile|_Atomic)\b[^;{{}}\n]*\b(?:{local}|{field[0]})\b', context):
            continue
        sites.append((*m.span('call'), f'({local} = {source[slice(*m.span("call"))]})'))
    sites = sites[:LIMIT]
    return [(FAMILY, edit(source, group)) for group in ([sites] + [[site] for site in sites] if len(sites) > 1 else [sites])
            if group]
