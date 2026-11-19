"""A symbol read through the pointer that was just set to its address.

m2c names a symbol directly where the game read it through a pointer it had just pointed at it:

    D_80102F40 = &D_800BF680;
    if (D_800BF680 != 0) {

gcc loads the symbol with its own `%hi`/`%lo` pair; the game loaded it through the address it already had in a
register (`lhu $v1, 0($v0)`). An N64 list walk was exact as `if (*D_80102F40 != 0)` (with its byte step fixed by
`pointer_byte_step`). Reads of the symbol between the assignment and the next store to the pointer or the symbol, or a
call, become `*P`; a hypothesis like every other family's, the judge decides.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'stored_pointer_read'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'


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
    for set_ in re.finditer(r'(?m)^[ \t]*(?P<p>' + IDENT + r')\s*=\s*&\s*(?P<s>' + IDENT + r')\s*;', clean[opening:end]):
        pointer, symbol = set_['p'], set_['s']
        start = opening + set_.end()
        # up to the next store to either, a call (it may change them), or the end of the function
        stop = re.search(r'(?<![\w.>])(?:' + pointer + '|' + symbol + r')\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*(?:'
                         + pointer + '|' + symbol + r')\b|\b(?:' + pointer + '|' + symbol + r')\s*(?:\+\+|--)|\b(?!if\b|while\b|for\b|switch\b|return\b|sizeof\b)'
                         + IDENT + r'\s*\(', clean[start:end])
        limit = start + stop.start() if stop else end
        reads = [m for m in re.finditer(r'(?<![\w.>&*])\b' + symbol + r'\b', clean[start:limit])]
        if not reads:
            continue
        text = source
        for m in reversed(reads):
            at = start + m.start()
            text = text[:at] + '*' + pointer + text[at + len(symbol):]
        result.append((FAMILY, text))
    return result[:4]
