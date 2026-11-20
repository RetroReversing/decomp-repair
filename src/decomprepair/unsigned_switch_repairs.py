"""A switch on a signed value compared as unsigned: `switch ((u32)x)`.

gcc 2.7.2 lowers a switch on a signed operand with a range split first (`slti` against the lowest case, then the
table or compare tree); on an unsigned operand one `sltiu` against the case count covers both ends. A game whose
code tests a switch with a single `sltiu` was written with an unsigned operand. An N64 function switching on four
small values was 830 points off with m2c's `s32` parameter and exact with `switch ((u32)arg1)`. The cast keeps the
meaning whenever every case label is a non-negative constant below 2**31 (a negative value matches none of them
either way), so the family offers it only then, one switch at a time.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'unsigned_switch'
FAMILIES = (FAMILY,)

SWITCH = re.compile(r'\bswitch\s*\(')
CASE = re.compile(r'\bcase\s+([^:]+?)\s*:')
NUMBER = re.compile(r'(0[xX][0-9a-fA-F]+|\d+)[uUlL]*')
UNSIGNED_CAST = re.compile(r'^\(\s*(?:u8|u16|u32|unsigned\b[^)]*)\s*\)')


def _value(text):
    m = NUMBER.fullmatch(text.strip())
    return int(m[1], 0) if m else None


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    result = []
    for sw in SWITCH.finditer(clean, span[0], span[1]):
        paren_end = close(clean, sw.end() - 1, '(', ')')
        if not paren_end:
            continue
        operand = source[sw.end():paren_end - 1].strip()
        if not operand or UNSIGNED_CAST.match(operand):
            continue
        opening = clean.find('{', paren_end, span[1])
        if opening < 0 or clean[paren_end:opening].strip():
            continue
        end = close(clean, opening, '{', '}')
        if not end:
            continue
        values = [_value(m[1]) for m in CASE.finditer(clean, opening, end)]
        if not values or any(v is None or v >= 2 ** 31 for v in values):
            continue  # (a label that isn't a plain non-negative number could change meaning under the cast)
        text = source[:sw.end()] + f'(u32)({operand})' + source[paren_end - 1:]
        if re.fullmatch(r'[A-Za-z_]\w*', operand):
            text = source[:sw.end()] + f'(u32){operand}' + source[paren_end - 1:]
        result.append((FAMILY, text))
        if len(result) >= 4:
            break
    return result
