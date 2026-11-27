"""A global only read (or plainly assigned) as a one-member record, and a loop-indexed array as records.

Matched on N64 menu handlers (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O1`, exact judge). For a scalar the target forms
the address once (`lui; addiu`, then `lh`/`lbu` through that register), above all in a loop, where a plain scalar is read
with `lui; lh %lo` each time. Declared `extern struct { s16 value; } G;` and read as `G.value`, the address is a value the
loop pass keeps in a register (265 -> 0 on a 430-instruction function). The reverse shape is the same fix for an array:
`u16 T[]` indexed in a loop had its address hoisted into a register where the target keeps `lui $v1; addu; lhu %lo(T)($v1)`;
as an array of one-member records the address is not hoisted (465 -> 0 on a 169-instruction function).

`global_scalar_record` (global_pointer_record.py) covers only globals updated in place; this one takes the rest.

Hypothesis, not traced through the compiler: a member access is `MEM_IN_STRUCT_P`, which changes what cse and loop.c do
with the address. The exact judge decides."""
import re

from .csource import _blank, find

FAMILY = 'global_read_record'
ELEMENTS = 'array_element_record'
FAMILIES = (FAMILY, ELEMENTS)
LIMIT = 8
TYPE = r'(?:[su](?:8|16|32)|char|short|int|unsigned\s+(?:char|short|int)|signed\s+(?:char|short|int)|float|f32)'
SCALAR = re.compile(rf'(?m)^extern[ \t]+(?P<type>{TYPE})[ \t]+(?P<name>[A-Za-z_]\w*)[ \t]*;')
ARRAY = re.compile(rf'(?m)^extern[ \t]+(?P<type>{TYPE})[ \t]+(?P<name>[A-Za-z_]\w*)[ \t]*\[[ \t]*\][ \t]*;')


def _usable(source, header, name, declaration):
    if header and re.search(rf'\b{name}\b', header):
        return False
    rest = _blank(source[:declaration.start()] + source[declaration.end():])
    return re.search(rf'(?<![\w\]\)] )(?<![\w\]\)])&\s*{name}\b', rest) is None


def _record(source, declaration, replacement, pattern, wrap):
    tail = source[declaration.end():]
    clean = _blank(tail)
    pieces, last = [], 0
    for hit in pattern.finditer(clean):
        end = wrap(clean, hit)
        if end is None:
            return None
        pieces.append(tail[last:end] + '.value')
        last = end
    if not pieces:
        return None
    return source[:declaration.start()] + replacement + ''.join(pieces) + tail[last:]


def _scalar_end(clean, hit):
    return hit.end()


def _element_end(clean, hit):
    """Past the subscript's closing bracket; None for a use that is not `T[i]` alone."""
    at = hit.end()
    if at >= len(clean) or clean[at] != '[':
        return None
    depth = 0
    for index in range(at, len(clean)):
        depth += (clean[index] == '[') - (clean[index] == ']')
        if depth == 0:
            return None if clean[index + 1:index + 2] == '[' else index + 1
    return None


def variants(source, name, header=''):
    if not find(source, name):
        return []
    out = []
    for family, declarations, suffix, end in ((FAMILY, SCALAR, '', _scalar_end),
                                              (ELEMENTS, ARRAY, '[]', _element_end)):
        for found in declarations.finditer(source):
            symbol = found['name']
            if not _usable(source, header, symbol, found):
                continue
            child = _record(source, found, f'extern struct {{ {found["type"]} value; }} {symbol}{suffix};',
                            re.compile(rf'\b{symbol}\b(?![ \t]*\.)'), end)
            if child:
                out.append((family, child))
            if len([f for f, _ in out if f == family]) >= LIMIT:
                break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
