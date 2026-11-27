"""A byte array indexed by `i * 2` or `i * 4` with the result written through, retyped as the table of that element.

m2c declares a table it has no type for as `extern char T[];` and writes an element as `*((i * 2) + T) = 0;`. That is
a byte store (`sb`) of the second byte's address; the game's table held halfwords, and the target stores `sh` (or reads
`lh`/`lhu`, `lw`) at the same address. The width cannot be reached by a rewrite of the index: the declaration and every
use change together.

Matched on an SN gcc 2.8.1 (`-G0 -mips3 -O2 -mfp64`) effect update of 71 instructions: `sh $zero` where the draft had
`sb` (500 -> 300 alone, 0 with the two other edits).

scaled_byte_table_element
    An `extern char T[];` (or `u8`, `s8`) the source declares itself, whose every use is `*((E * N) + T)` or
    `*(T + (E * N))` with one N of 2 or 4, becomes `extern u16 T[];` (and `s16`), or `extern s32 T[];` for 4, and each
    use `T[E]`. One child per table and element type.
"""
import re

from .csource import _blank
from .pattern_repairs import _close

FAMILY = 'scaled_byte_table_element'
FAMILIES = (FAMILY,)
LIMIT = 6
TYPES = {2: ('u16', 's16'), 4: ('s32',)}

_TABLE = re.compile(r'(?m)^extern[ \t]+(?:(?:unsigned|signed)[ \t]+char|char|u8|s8)[ \t]+(?P<name>[A-Za-z_]\w*)'
                    r'[ \t]*\[[ \t]*\][ \t]*;')
_OPERAND = re.compile(r'(?:\([A-Za-z_][\w \t*]*\)\s*)?\w+')
_MEMBER = re.compile(r'\s*(?:\.|->)\s*\w+')


def _group(text):
    """True when the whole text is one bracket group."""
    return text.startswith('(') and _close(text, 0) == len(text)


def _primary(text):
    """True for one operand: a bracket group, or a name with its casts, members, calls and subscripts."""
    if _group(text):
        return True
    head = _OPERAND.match(text)
    if not head:
        return False
    at = head.end()
    while at < len(text):
        step = _MEMBER.match(text, at)
        if step:
            at = step.end()
        elif text[at] in '([':
            at = _close(text, at, text[at], ')' if text[at] == '(' else ']') or len(text) + 1
        else:
            return False
    return at == len(text)


def _element(inner, table):
    """(index, size) of `(index * size) + table` in either order, or None."""
    inner = inner.strip()
    other = re.fullmatch(rf'(?s)(?:{table}[ \t]*\+(.*)|(.*)\+[ \t]*{table})', inner)
    if not other:
        return None
    product = (other[1] or other[2]).strip()
    if not _group(product):
        return None
    scaled = re.fullmatch(r'(?s)(.*\S)\s*\*\s*([24])', product[1:-1].strip())
    if not scaled or not _primary(scaled[1]):
        return None
    index = scaled[1][1:-1].strip() if _group(scaled[1]) else scaled[1]
    return index, int(scaled[2])


def _uses(body, table):
    """[(start, end, index, size)] for every use of the table, or None when one use is of another form."""
    clean = _blank(body)
    found = []
    for opening in re.finditer(r'\*[ \t]*\(', clean):
        before = clean[:opening.start()].rstrip()
        if before and (before[-1].isalnum() or before[-1] in '_)]'):
            continue
        start = opening.end() - 1
        end = _close(clean, start)
        if end is None or not re.search(rf'\b{table}\b', clean[start:end]):
            continue
        element = _element(body[start + 1:end - 1], table)
        if element:
            found.append((opening.start(), end, *element))
    if len(found) != len(re.findall(rf'\b{table}\b', clean)) or len({size for *_, size in found}) != 1:
        return None
    return found


def variants(source, name, header=''):
    result = []
    for declared in _TABLE.finditer(source):
        table = declared['name']
        if header and re.search(rf'\b{table}\b', header):
            continue
        body = source[declared.end():]
        uses = _uses(body, table)
        if not uses:
            continue
        pieces, last = [], 0
        for start, end, index, _ in uses:
            pieces.append(body[last:start] + f'{table}[{index}]')
            last = end
        rewritten = ''.join(pieces) + body[last:]
        for kind in TYPES[uses[0][3]]:
            result.append((FAMILY, source[:declared.start()] + f'extern {kind} {table}[];' + rewritten))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
