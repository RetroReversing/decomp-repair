"""Stage a signed record field before a witnessed global float store."""

import re
import struct

from .integer_repair_support import IDENT, NUMBER, edit, integer
from .operand_lifetime_repairs import _visible

FAMILY = 'halfword_before_float_store'
FRESH = 'repair_signed_field'
REG = r'\$\w+'
WORD = r'(?:0[xX][0-9a-fA-F]+|\d+)'
_PTR = re.compile(rf'lw ({REG}), ({WORD})\(({REG})\)')
_FIELD = re.compile(rf'lh ({REG}), ({WORD})\(({REG})\)')
_STORE = re.compile(rf'swc1 ({REG}), %lo\(({IDENT})\)\(\$at\)')
_COMPARE = re.compile(rf'slti ({REG}), ({REG}), ({WORD})')
_UPPER = re.compile(rf'lui \$at, ({WORD})')
_LOWER = re.compile(rf'ori \$at, \$at, ({WORD})')
_SOURCE = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)(?P<symbol>{IDENT})\s*=\s*'
    r'(?P<float>\d+\.\d+[fF])\s*;[ \t]*\n'
    rf'[ \t]*if\s*\(\s*(?P<field>[^;<>&=\n]+?)\s*<\s*(?P<limit>{NUMBER})\s*\)'
)


def _load(expression, type_):
    return re.fullmatch(
        rf'\(\*\(\({re.escape(type_)}\*\)\(\(\(char\*\)(?P<base>.+)\)\+(?P<offset>{NUMBER})\)\)\)',
        expression,
    )


def _targets(rows):
    target = [(mark != ' ', left) for mark, left, _ in rows if left]
    candidate = [(mark != ' ', right) for mark, _, right in rows if right]
    later = {
        (m[2], pointer[2], read[2])
        for (_, store), (p_changed, ptr), (f_changed, field) in zip(candidate, candidate[1:], candidate[2:])
        if (p_changed or f_changed) and (m := _STORE.fullmatch(store))
        and (pointer := _PTR.fullmatch(ptr)) and (read := _FIELD.fullmatch(field)) and read[3] == pointer[1]
    }
    hits = set()
    for i in range(6, len(target) - 1):
        changed, store = target[i]
        if not (written := _STORE.fullmatch(store)):
            continue
        ptr, upper, lower, move, half, address = (line for _, line in target[i - 6:i])
        data = _PTR.fullmatch(ptr), _UPPER.fullmatch(upper), _LOWER.fullmatch(lower), _FIELD.fullmatch(half)
        compare = _COMPARE.fullmatch(target[i + 1][1])
        if not all(data) or not compare:
            continue
        pointer, hi, lo, field = data
        register, symbol = written.groups()
        if ((symbol, pointer[2], field[2]) not in later or field[3] != pointer[1] or compare[2] != field[1]
                or address != f'lui $at, %hi({symbol})' or move != f'mtc1 $at, {register}'):
            continue
        if not changed and not any(flag for flag, _ in target[i - 6:i]):
            continue
        bits = (integer(hi[1]) << 16) | integer(lo[1])
        hits.add((symbol, integer(pointer[2]), integer(field[2]), integer(compare[3]), bits))
    return hits


def variants(source, name, rows, *, header=''):
    targets = _targets(rows)
    visible = _visible(source, name, header) if targets else None
    if not visible:
        return []
    part, context = visible
    if re.search(rf'\b{FRESH}\b', context):
        return []
    options = []
    for m in _SOURCE.finditer(part.clean, part.opening + 1, part.end):
        field = _load(re.sub(r'\s+', '', m['field']), 's16')
        pointer = _load(field['base'], 'void*') if field else None
        if not pointer or not re.fullmatch(IDENT, pointer['base']):
            continue
        try:
            single = struct.unpack('>I', struct.pack('>f', float(m['float'][:-1])))[0]
        except OverflowError:
            continue
        key = (m['symbol'], integer(pointer['offset']), integer(field['offset']), integer(m['limit']), single)
        if key not in targets or not re.search(rf'\bextern\s+f32\s+{m["symbol"]}\s*;', context):
            continue
        if re.search(rf'\b(?:f32|float)\s+{m["symbol"]}\b', part.body):
            continue
        before = part.clean[part.opening + 1:m.start()].rstrip()
        if (before and before[-1] not in ';{}:') or re.search(r'/[*/]|#', source[m.start():m.end()]):
            continue
        objects = '|'.join((pointer['base'], m['symbol']))
        names = '|'.join((objects, 's16', 's32', 'f32'))
        if re.search(rf'(?m)^\s*#\s*(?:define|undef)\s+(?:{names})\b|'
                     rf'\b(?:volatile|_Atomic)\b[^;{{}}\n]*\b(?:{objects})\b|'
                     r'\btypedef\b[^;\n]*\bvolatile\b[^;\n]*\b(?:s16|s32|f32)\s*;', context):
            continue
        prefix = f'{m["indent"]}{FRESH} = {source[slice(*m.span("field"))]};\n'
        options.append(edit(source, [
            (part.opening + 1, part.opening + 1, f'\n    s32 {FRESH};'),
            (m.start(), m.start(), prefix),
            (*m.span('field'), FRESH),
        ]))
    return [(FAMILY, options[0])] if len(options) == 1 else []
