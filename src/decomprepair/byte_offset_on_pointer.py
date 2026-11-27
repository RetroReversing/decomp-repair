"""A byte offset m2c added to a typed pointer, so the compiler scales it a second time.

m2c keeps a loop's `i << 2` in a local and then adds it to a field it typed as a pointer to words:

    temp_s1 = i * 4;
    if (*(temp_s1 + M2C_FIELD(arg0, void ***, 0xC)) != 0) { ...
        v = *(temp_s1 + M2C_FIELD(arg0, void ***, 0x10));

C scales `temp_s1` by the element size again, so the compiled index is `i << 4` where the target has `sll $s1,$s3,2`.
The target adds the offset as bytes, offset first (an integer sum: `addu $v0,$s1,$v0`; a `u8 *` sum puts the pointer
first):

        v = *(void **)(temp_s1 + (s32)(M2C_FIELD(arg0, void ***, 0x10)));

On a 155-instruction sound-bank start (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`) this took the version with its
rebase loops already written as a helper from 188 to 38 (one function).

The child changes what the C computes: the draft's address was wrong. It is only offered when every assignment of the
offset local is a multiple of exactly the element's size, so the byte form is the one that matches how the offset was
made. Only reads and tests are rewritten, never a store. The candidate is never a verdict: the judge decides.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'byte_offset_on_pointer'
FAMILIES = (FAMILY,)

_ID = r'[A-Za-z_]\w*'
_SIZES = {'s8': 1, 'u8': 1, 'char': 1, 's16': 2, 'u16': 2, 's32': 4, 'u32': 4, 'int': 4, 'f32': 4}
_USE = re.compile(rf'\*\s*\(\s*(?P<offset>{_ID})\s*\+\s*(?=M2C_FIELD\s*\()')
_TYPE = re.compile(r'\s*(?P<base>void|s8|u8|char|s16|u16|s32|u32|int|f32)\s*(?P<stars>(?:\*\s*)+)$')


def _scale(value):
    """The byte multiple an offset expression is made with: `i * 4` and `i << 2` give 4."""
    hit = re.fullmatch(rf'\(?\s*{_ID}\s*(?:\*\s*(?P<times>0[xX][0-9A-Fa-f]+|\d+)|<<\s*(?P<shift>\d+))\s*\)?',
                       value.strip())
    if not hit:
        return None
    return int(hit['times'], 0) if hit['times'] else 1 << int(hit['shift'])


def _element(kind):
    """The type and size of `field[0]` for a field read as `M2C_FIELD(.., kind, ..)`, or None."""
    hit = _TYPE.fullmatch(kind)
    if not hit:
        return None
    stars = hit['stars'].count('*')
    if stars < 2:  # the field itself is not a pointer
        return None
    left = stars - 2  # one star for the access, one for the index
    if left:
        return f'{hit["base"]} {"*" * left}', 4
    size = _SIZES.get(hit['base'])
    return (hit['base'], size) if size else None


def variants(source, name):
    """Every `*(offset + M2C_FIELD(..))` with a byte offset, written as the byte access, as one child."""
    if 'M2C_FIELD' not in source:
        return []
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    body = clean[span[0]:span[1]]
    edits = []
    for hit in _USE.finditer(clean, span[0], span[1]):
        opening = clean.index('(', hit.start())
        end = close(clean, opening, '(', ')')
        field = hit.end()
        stop = end and close(clean, clean.index('(', field), '(', ')')
        if not stop or clean[stop:end - 1].strip():
            continue
        if re.match(r'\s*(?:=(?!=)|(?:[-+*/%&|^]|<<|>>)=|\+\+|--)', clean[end:]):
            continue
        before = clean[:hit.start()].rstrip()
        if not before or before[-1] not in '=(!&|,?:{;+-' and not before.endswith('return'):
            continue
        inner = clean[clean.index('(', field) + 1:stop - 1].split(',')
        element = _element(inner[-2]) if len(inner) >= 3 else None
        if not element:
            continue
        offset = hit['offset']
        values = [m[1] for m in re.finditer(rf'(?<![\w.>]){offset}\s*=(?!=)\s*([^;{{}}]*);', body)]
        if not values or any(_scale(value) != element[1] for value in values) or element[1] == 1:
            continue
        if re.search(rf'(?<![\w.>]){offset}\s*(?:[-+*/%&|^]|<<|>>)=|(?:\+\+|--)\s*{offset}\b|\b{offset}\s*(?:\+\+|--)',
                     body):
            continue
        text = f'*({element[0].strip()} *)({offset} + (s32)({source[field:stop]}))'
        edits.append((hit.start(), end, text))
    if not edits:
        return []
    child = source
    for start, end, text in reversed(edits):
        child = child[:start] + text + child[end:]
    return [(FAMILY, child)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
