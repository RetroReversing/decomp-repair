"""A narrow extern read at `index * K` bytes, written as pointer arithmetic that scales by the type: the byte-offset cast.

    extern u16 D_800B3022;   ...   *(&D_800B3022 + ((i & 0xFFFF) * 4))
 -> *(u16 *)((u8 *)&D_800B3022 + ((i & 0xFFFF) << 2))

m2c reads a table of 4-byte records whose first field is a halfword as `&sym + index * 4`; in C the `+` on a `u16 *`
scales by 2, so the compiler shifts by 3 where the game's code shifted by 2 (a 150-point difference, one `sll`, on a
KMC GCC 2.7.2 `-O2` search loop). The index is a byte count: the sum goes through `(u8 *)` and the load is cast back
to the symbol's own type. Offered for a scalar `extern` of a type narrower than the scale (`u8`, `s8`, `u16`, `s16`,
`char`, `short`) read as `*(&sym + (EXPR * K))` or `(EXPR << n)`. `narrow_table_byte_offset`: the shift when K is a
power of two, a product otherwise. A candidate for the exact judge."""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'narrow_table_byte_offset'
FAMILIES = (FAMILY,)
SIZES = {'u8': 1, 's8': 1, 'char': 1, 'u16': 2, 's16': 2, 'short': 2}
SITE = re.compile(rf'\*\s*\(\s*&\s*(?P<sym>{IDENT})\s*\+\s*\(')
SCALE = re.compile(r'^(?P<expr>.+?)\s*(?P<op>\*|<<)\s*(?P<k>\d+)\s*$', re.S)


def _type(sym, text):
    hit = re.search(rf'\bextern\s+(?:const\s+)?(?P<t>{"|".join(SIZES)})\s+{re.escape(sym)}\s*;', text)
    return hit['t'] if hit else None


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    edits = []
    for site in SITE.finditer(part.clean, part.opening, part.end):
        kind = _type(site['sym'], source + '\n' + (header or ''))
        inner_open = site.end() - 1
        stop = close(part.clean, inner_open)
        tail = re.match(r'\s*\)', part.clean[stop:]) if stop else None
        if not kind or not tail:
            continue
        inner = source[inner_open + 1:stop - 1]
        scale = SCALE.match(inner)
        if not scale or scale['expr'].count('(') != scale['expr'].count(')'):
            continue
        k = int(scale['k'])
        bytes_ = k if scale['op'] == '*' else 1 << k
        if bytes_ <= SIZES[kind] or bytes_ & (bytes_ - 1) and scale['op'] == '<<':
            continue
        shifted = f'{scale["expr"]} << {bytes_.bit_length() - 1}' if bytes_ & (bytes_ - 1) == 0 else f'{scale["expr"]} * {bytes_}'
        edits.append((site.start(), stop + tail.end(),
                      f'*({kind} *)((u8 *)&{site["sym"]} + ({shifted}))'))
    return [(FAMILY, edit(source, edits))] if edits else []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}
