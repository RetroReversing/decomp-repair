"""m2c's unaligned four-byte copy, written as the `__builtin_memcpy` it came from.

A four-byte `strcpy` or `memcpy` between byte buffers is `lwl`/`lwr` and `swl`/`swr`. m2c writes it as a word store of
`M2C_UNALIGNED32(...)`, which no compiler turns back into those instructions:

    *(s32 *)(temp + D_80072A30) = M2C_UNALIGNED32(D_8000429C);
      ->  __builtin_memcpy((char *) (temp + D_80072A30), (char *) D_8000429C, 4);

The `char *` casts keep the compiler from assuming word alignment. Found on an N64 table insertion (SN64 GCC 2.8.1)
that copies a three-letter default name into a four-byte entry; the original was probably a `strcpy` of a literal,
which this reaches without reading the string's bytes. Children: every such copy at once, then each alone.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'unaligned_word_memcpy'
FAMILIES = (FAMILY,)
LIMIT = 6
_ID = r'[A-Za-z_]\w*'
_MARK = re.compile(r'=\s*M2C_UNALIGNED32\s*\(')
_FIELD = re.compile(r'M2C_FIELD\(\s*(?P<base>[^;{}]+?)\s*,\s*[^,;{}()]+?\*\s*,\s*'
                    r'(?P<offset>-?(?:0[xX][0-9A-Fa-f]+|\d+))\s*\)\Z')
_DEREF = re.compile(r'\*\s*\(\s*(?:s32|u32|int|M2C_UNK|M2C_UNK32)\s*\*\s*\)\s*(?P<at>\(.*\)|[A-Za-z_]\w*)\Z', re.S)


def variants(source, name):
    span = find(source, name)
    if not span or 'M2C_UNALIGNED32' not in source:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0])
    if opening < 0:
        return []
    edits = []
    for hit in _MARK.finditer(clean, opening, span[1]):
        begin = max(clean.rfind(mark, opening, hit.start()) for mark in ';{}') + 1
        begin += len(clean[begin:hit.start()]) - len(clean[begin:hit.start()].lstrip())
        end = close(clean, hit.end() - 1)
        semicolon = re.compile(r'\s*;').match(clean, end) if end else None
        if not semicolon:
            continue
        to = _address(source[begin:hit.start()].strip(), clean)
        origin = _address(source[hit.end():end - 1].strip(), clean)
        if to and origin:
            edits.append((begin, semicolon.end(), f'__builtin_memcpy((char *) {to}, (char *) {origin}, 4);'))
    if not edits:
        return []
    groups = [edits] + ([[one] for one in edits] if len(edits) > 1 else [])
    out = []
    for group in groups[:LIMIT]:
        child = source
        for begin, end, text in reversed(group):
            child = child[:begin] + text + child[end:]
        out.append((FAMILY, child))
    return out


def _address(access, context):
    """The address of the word `access` reads or writes, as an expression, or None."""
    field = _FIELD.match(access)
    if field:
        return f'((char *) ({field["base"]}) + {field["offset"]})'
    deref = _DEREF.match(access)
    if deref:
        at = deref['at']
        return at if not at.startswith('(') or close(at, 0) == len(at) else None
    if re.match(rf'{_ID}\Z', access):
        # a symbol m2c reads by name: an array is its own address, a scalar's is taken
        if re.search(rf'\b{access}\s*\[', context):
            return access
        return f'&{access}' if re.search(rf'\bextern\b[^;{{}}()]*\b{access}\s*;', context) else None
    return None


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 30}
