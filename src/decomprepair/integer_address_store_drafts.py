"""Give m2c's `*(integer expression) = value;` the width of the store in the target.

When m2c can't type the address of a store it writes the dereference of an integer expression,
`*((*count * 0xA10) + base) = 0;`, which no C compiler accepts, so the whole draft failed and nothing downstream ran. The
original instruction says how wide the store is: `sh $zero, 0($v0)` is a halfword. The rewrite writes
`*(u16 *)(...)` for each store width the function's code has through a register (not the stack, not a named global),
most frequent first; the compiler and the judge decide which is right.
"""
import re
from collections import Counter

from .integer_repair_support import edit, view

FAMILY = 'integer_address_store'
FAMILIES = (FAMILY,)
LIMIT = 3
WIDTHS = {'sb': 'u8', 'sh': 'u16', 'sw': 's32'}
_STORE = re.compile(r'(?m)^[^\n]*?\b(sb|sh|sw)\s+\$\w+,\s*(?:-?0x[0-9A-Fa-f]+|-?\d+)\(\$(?!sp\b)\w+\)')
_UNTYPED = re.compile(r'(?m)^([ \t]*)\*(\((?:[^;{}]*)\))[ \t]*=(?!=)([^;{}]+);')
_CAST = re.compile(r'\((?:[su](?:8|16|32|64)|f(?:32|64)|void|char|short|int|long|unsigned)\b[^()]*\*+\s*\)')


def _widths(asm):
    counts = Counter(WIDTHS[m[1]] for m in _STORE.finditer(asm))
    return [width for width, _ in counts.most_common(LIMIT)]


def variants(source, name, asm):
    part = view(source, name)
    if not part:
        return []
    base = part.opening + 1
    sites = []
    for match in _UNTYPED.finditer(part.clean[base:part.end]):
        expression = match[2]
        # only an address built by arithmetic with no cast: `*(p)` or `*(T *)(...)` is typed already
        if _CAST.search(expression) or not re.search(r'[+*]', expression):
            continue
        sites.append((base + match.start(2), base + match.end(2)))
    if not sites:
        return []
    return [(FAMILY, edit(source, [(a, a, '(' + width + ' *)') for a, _ in sites])) for width in _widths(asm)]
