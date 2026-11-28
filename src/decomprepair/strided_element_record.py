"""A symbol's byte-strided elements, `(char *) &D + i * K`, written as the array of K-byte records they are.

m2c declares a table of records as one byte or word and walks it with a cursor; once the cursor is written as the
counter's multiple (`integer_cursor_for_loop`), every field is an offset off the same sum:

    extern u8 D_80001000;                       typedef struct { char pad0[0x40]; s32 m40; s32 m44; } __repair_element;
    x = M2C_FIELD(((char *)(&D_80001000)        extern __repair_element D_80001000[];
                   + i * 0x48), s32 *, 0x40);   x = D_80001000[i].m40;
    y = M2C_FIELD(... , s32 *, 0x44);      ->   y = D_80001000[i].m44;
    draw(0, ((char *)(&D_80001000) + i * 0x48));  draw(0, (void *) &D_80001000[i]);

GCC's loop pass reduces each spelling differently: the byte sums became two stepped pointers (the symbol and the symbol
plus 0x44) beside the cursor, the record array one pointer stepped by the record's size with the fields as offsets, as
the target has. `record_field_array` is the same for fields m2c named by their own addresses, `global_offset_records`
for constant offsets off one global. Only when the symbol is declared in the source and every use of it is this sum
with one index and one stride. On a 461-instruction N64 menu screen (SN64 GCC 2.8.1) this step alone took a chain from
2495 to 850.
"""
import re

from .csource import _blank, find
from .integer_repair_support import split_args
from .pattern_repairs import close

FAMILY = 'strided_element_record'
FAMILIES = (FAMILY,)
IDENT = r'[A-Za-z_]\w*'
NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)'
SIZES = {'s8': 1, 'u8': 1, 's16': 2, 'u16': 2, 's32': 4, 'u32': 4, 'f32': 4, 'M2C_UNK': 4, 'M2C_UNK8': 1, 'M2C_UNK16': 2}
SUM = re.compile(rf'\(\s*\(\s*(?:char|s8|u8)\s*\*\s*\)\s*(?:\(\s*&\s*(?P<a>{IDENT})\s*\)|&\s*(?P<b>{IDENT}))\s*\+\s*'
                 rf'(?P<index>{IDENT})\s*\*\s*(?P<stride>{NUMBER})\s*\)')
FIELD = re.compile(r'\bM2C_FIELD\s*\(')


def _record(source, clean, span, symbol, sums):
    """The edits that make `symbol` a record array, or None."""
    declared = re.search(rf'(?m)^[ \t]*extern[ \t]+(?:{"|".join(SIZES)})[ \t]+{symbol}[ \t]*(?:\[\s*\])?[ \t]*;[ \t]*\n',
                         clean)
    if not declared or len({(s['index'], int(s['stride'], 0)) for s in sums}) != 1:
        return None
    index, stride = sums[0]['index'], int(sums[0]['stride'], 0)
    inside = [use.start() for use in re.finditer(rf'(?<![\w.>]){symbol}(?!\w)', clean[span[0]:span[1]])]
    if len(inside) != len(sums) or any(use.start() < declared.start() or use.start() >= declared.end()
                                       for use in re.finditer(rf'(?<![\w.>]){symbol}(?!\w)', clean[:span[0]])):
        return None
    members, edits, taken = {}, [], set()
    for hit in FIELD.finditer(clean, span[0], span[1]):
        end = close(clean, hit.end() - 1, '(', ')')
        if not end:
            return None
        args = split_args(clean[hit.end():end - 1])
        if len(args) != 3:
            continue
        base = clean[hit.end() + args[0][0]:hit.end() + args[0][1]].strip()
        found = SUM.fullmatch(base)
        if not found or (found['a'] or found['b']) != symbol:
            continue
        kind = re.fullmatch(r'\s*(\w+)\s*\*\s*', clean[hit.end() + args[1][0]:hit.end() + args[1][1]])
        offset = clean[hit.end() + args[2][0]:hit.end() + args[2][1]].strip()
        if not kind or kind[1] not in SIZES or not re.fullmatch(NUMBER, offset):
            return None
        at, size = int(offset, 0), SIZES[kind[1]]
        if at % size or at + size > stride or members.setdefault(at, (kind[1], size)) != (kind[1], size):
            return None
        edits.append((hit.start(), end, f'{symbol}[{index}].m{at:X}'))
        taken.add(clean.find(symbol, hit.end(), end))
    if not members:
        return None
    for found in sums:
        if found.start() + found[0].find(symbol) not in taken:
            edits.append((found.start(), found.end(), f'((void *) &{symbol}[{index}])'))
    lines, at = [], 0
    for offset, (kind, size) in sorted(members.items()):
        if offset < at:
            return None
        if offset > at:
            lines.append(f'    char pad{at:X}[0x{offset - at:X}];')
        lines.append(f'    {kind} m{offset:X};')
        at = offset + size
    if stride > at:
        lines.append(f'    char pad{at:X}[0x{stride - at:X}];')
    tag = f'__repair_element_{symbol}'
    text = 'typedef struct {\n' + '\n'.join(lines) + f'\n}} {tag};\nextern {tag} {symbol}[];\n'
    edits.append((declared.start(), declared.end(), text))
    return edits


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    by_symbol = {}
    for hit in SUM.finditer(clean, span[0], span[1]):
        by_symbol.setdefault(hit['a'] or hit['b'], []).append(hit)
    edits = []
    for symbol, sums in by_symbol.items():
        found = _record(source, clean, span, symbol, sums)
        if found:
            edits += found
    if not edits:
        return []
    text = source
    for start, end, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[end:]
    return [(FAMILY, text)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
