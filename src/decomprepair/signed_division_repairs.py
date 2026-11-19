"""m2c's expansion of a signed division by a power of two, written back as `/` and `%`.

gcc divides a signed value by 2^N with a shift and a correction for negative values; m2c reads that back as

    q = t >> 0x10;
    if (t < 0) {
        q = (s32) (t + 0xFFFF) >> 0x10;
    }
    ... (t - (q << 0x10)) ...

which compiles to the same steps but not the same registers: an N64 function was 99.8% so and exact as
`t % 0x10000` (the quotient, where it is used as one, becomes `t / 0x10000`).
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'signed_division'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
NUMBER = r'0[xX][0-9a-fA-F]+|\d+'
SHAPE = re.compile(
    r'(?m)^[ \t]*(?P<q>' + IDENT + r')\s*=\s*(?P<t>' + IDENT + r')\s*>>\s*(?P<n>' + NUMBER + r')\s*;[ \t]*\n'
    r'[ \t]*if\s*\(\s*(?P=t)\s*<\s*0\s*\)\s*\{\s*\n'
    r'[ \t]*(?P=q)\s*=\s*(?:\(\s*s32\s*\)\s*)?\(\s*(?P=t)\s*\+\s*(?P<c>' + NUMBER + r')\s*\)\s*>>\s*(?P=n)\s*;\s*\n'
    r'[ \t]*\}[ \t]*\n')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    result = []
    for hit in SHAPE.finditer(clean, opening, end):
        n, c = int(hit['n'], 0), int(hit['c'], 0)
        if c != (1 << n) - 1:
            continue
        q, t, power = hit['q'], hit['t'], f'0x{1 << n:X}'
        rest = source[hit.end():end]
        rest = re.sub(r'\(\s*' + t + r'\s*-\s*\(\s*' + q + r'\s*<<\s*' + hit['n'] + r'\s*\)\s*\)', f'({t} % {power})', rest)
        rest = re.sub(r'(?<![\w.>])' + q + r'\b', f'({t} / {power})', rest)
        text = source[:hit.start()] + rest + source[end:]
        declared = re.search(r'(?m)^[ \t]*[\w ]+?\s+' + q + r'\s*;[ \t]*\n', text[opening:])
        if declared and not re.search(r'(?<![\w.>])' + q + r'\b', text[opening + declared.end():]):
            text = text[:opening + declared.start()] + text[opening + declared.end():]
        result.append((FAMILY, text))
    return result[:2]
