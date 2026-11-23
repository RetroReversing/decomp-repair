"""A base pointer set before a loop from a symbol, `P = ((u8 *) Q) - K;`, whose reads are all `P[N]`: read the symbol directly.

m2c writes the flag bytes a loop tests as one pointer local derived from a global's address (`modeFlags =
((u8 *) &D_8010A4E4) - 0x21;`, then `modeFlags[0]`, `modeFlags[-1]`, `modeFlags[-2]`). The game read the symbol: each
test is `((u8 *) &SYM)[N - K]`, and GCC 2.7.2 derives the base itself. cse's related-value machinery turns the first
`SYM - K` into one `addiu base, symbolreg, -K` and the other tests into offsets from it, and that add is an invariant
that loop.c hoists *as a movable*, so it lands in the loop's preheader in order of first use, among the constants the
loop uses (an `li.s` pair, a hoisted `0xff`), where a user-written pointer local sits first of all, ahead of them. The
instruction is the same; only its place in the preheader differs, so the diff is two reordered rows that no statement
order of the surrounding assignments moves (all 24 orders of the four statements before the loop were tried).

The case (KMC GCC 2.7.2, `-O2 -G0 -mips3`, a 511-instruction display-list submit function with a per-view loop): the
two `o` rows (`addiu $s5, $v1, -0x21` first in the preheader, the target has it after the second float constant)
disappeared, 85 -> 25; the five rows left were registers of an unrelated pointer. The scheduler/loop reading is from
cse.c (`use_related_value`) and loop.c (`move_movables`) and is a hypothesis; the judge decides each child.

The child (`symbol_offset_base_inline`, one per base pointer) deletes the assignment and the local's declaration and
spells every `P[N]` as `((T *) &SYM)[N - K]` (`N + K` for a `+`), when:
- `P` is a pointer local declared in the function, assigned once, by `((T *) Q) +/- K` with `K` an integer literal;
- `Q` is `&SYM`, or a local assigned once, to `&SYM`;
- every other mention of `P` is `P[integer literal]`.
"""
import re

from .csource import _blank, find
from .reassigned_local_inline import IDENT

FAMILY = 'symbol_offset_base_inline'
FAMILIES = (FAMILY,)
LIMIT = 4
NUMBER = r'0[xX][0-9A-Fa-f]+|\d+'
TYPE = r'(?:unsigned\s+)?(?:u8|s8|u16|s16|u32|s32|char|short|int|long|f32|f64|float|double)'


def _number(text):
    sign = -1 if text.strip().startswith('-') else 1
    digits = text.strip().lstrip('+-').strip()
    return sign * int(digits, 16 if digits[:2] in ('0x', '0X') else 10), digits[:2] in ('0x', '0X')


def _spell(value, hexadecimal):
    if hexadecimal:
        return f'-0x{-value:X}' if value < 0 else f'0x{value:X}'
    return str(value)


def _origin(clean, opening, end, base):
    """The symbol a base names: `&SYM` itself, or a local assigned once, by `&SYM`."""
    if base.startswith('&'):
        return base[1:]
    window = clean[opening:end]
    sets = [m for m in re.finditer(rf'(?<![\w.>]){re.escape(base)}\s*=(?!=)', window)]
    origin = [m for m in re.finditer(rf'(?<![\w.>]){re.escape(base)}\s*=\s*&\s*({IDENT})\s*;', window)]
    if len(sets) != 1 or len(origin) != 1:
        return None
    return origin[0][1]


def _whole_line(clean, first, last, end):
    """(start, stop) of the line holding a statement that is alone on it; None when something else shares it."""
    begin = clean.rfind('\n', 0, first) + 1
    stop = clean.find('\n', last)
    stop = end if stop < 0 else stop
    if clean[begin:first].strip() or clean[last:stop].strip():
        return None
    return begin, stop + 1


def variants(source, name):
    clean = _blank(source)
    span = find(source, name)
    if not span:
        return []
    start, end = span
    opening = clean.find('{', start, end)
    if opening < 0 or 'volatile' in clean[opening:end]:
        return []
    assign = re.compile(
        rf'(?<![\w.>])({IDENT})\s*=\s*(?:\(\s*\(\s*({TYPE})\s*\*\s*\)\s*(&?\s*{IDENT})\s*\)'
        rf'|\(\s*({TYPE})\s*\*\s*\)\s*(&?\s*{IDENT}))\s*([-+])\s*({NUMBER})\s*;')
    result = []
    for hit in assign.finditer(clean, opening, end):
        pointer, sign, literal = hit[1], hit[6], hit[7]
        cast = hit[2] or hit[4]
        symbol = _origin(clean, opening, end, re.sub(r'\s+', '', hit[3] or hit[5]))
        if symbol is None or not re.search(rf'\b{re.escape(symbol)}\b', clean[:opening]):
            continue
        declared = list(re.finditer(rf'(?:register\s+)?{TYPE}\s*\*\s*{re.escape(pointer)}\s*;', clean[opening:end]))
        if len(declared) != 1:
            continue
        declaration = _whole_line(clean, opening + declared[0].start(), opening + declared[0].end(), end)
        statement = _whole_line(clean, hit.start(), hit.end(), end)
        if declaration is None or statement is None:
            continue
        delta = _number(literal)[0] * (-1 if sign == '-' else 1)
        edits = [(declaration[0], declaration[1], ''), (statement[0], statement[1], '')]
        for use in re.finditer(rf'(?<![\w.>]){re.escape(pointer)}\b', clean[opening:end]):
            at = opening + use.start()
            if declaration[0] <= at < declaration[1] or statement[0] <= at < statement[1]:
                continue
            access = re.match(rf'\s*\[\s*(-?\s*(?:{NUMBER}))\s*\]', clean[opening + use.end():end])
            if not access:
                edits = None
                break
            index, hexadecimal = _number(access[1])
            edits.append((at, opening + use.end() + access.end(), f'(({cast} *) &{symbol})[{_spell(index + delta, hexadecimal)}]'))
        if not edits or len(edits) == 2:
            continue
        text = source
        for first, last, replacement in sorted(edits, reverse=True):
            text = text[:first] + replacement + text[last:]
        if text != source and text not in result:
            result.append(text)
    return [(FAMILY, text) for text in result[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 60}  # the registry: no caller wiring (registry.py)
