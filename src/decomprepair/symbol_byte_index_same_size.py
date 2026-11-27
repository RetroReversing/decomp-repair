"""A word symbol indexed by bytes that m2c wrote as a scaled element index: `*(&D + (n * 4))` for a 4-byte `D`.

    extern f32 D_80122530;   ...   *(&D_80122530 + (func_800E2DA0(arg0) * 4)) = (f32) best;
 -> *(&D_80122530 + func_800E2DA0(arg0)) = (f32) best;            (the step is the element)
 -> *(f32 *)((s8 *)&D_80122530 + (func_800E2DA0(arg0) * 4)) = (f32) best;       (the step is bytes)

m2c reads a table of words as `&sym + index * 4` and writes it with the byte step, but in C the `+` on an `f32 *`
scales by 4 again: the compiler shifts by 4 where the game's code shifted by 2 (a 150-point difference, one `sll`, with
every other row exact, in an SN GCC 2.7.2 `-O2` function that stores a float at a per-index slot of a small table).
`narrow_table_byte_offset` covers a symbol narrower than the step (a halfword read at `index * 4`); this is the step
equal to the element (or smaller than it), where the element index alone, `&D + n`, and the byte-offset cast both give
the target's `sll 2` (both measured 0 on that function, the first being the one the game most likely wrote).

Offered for `*(&SYM + (EXPR * K))` or `(EXPR << n)` where SYM is a scalar `extern` of 2, 4 or 8 bytes (`s16`, `u16`,
`s32`, `u32`, `int`, `f32`, `f64`, `s64`, `u64`) and the step in bytes K is a power of two no larger than the element:
one child per form, each rewriting every such site: the element index (only when K equals the element size) and the
byte-offset cast. A candidate for the exact judge.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'symbol_byte_index_same_size'
FAMILIES = (FAMILY,)
SIZES = {'s16': 2, 'u16': 2, 'short': 2, 's32': 4, 'u32': 4, 'int': 4, 'f32': 4, 'float': 4, 's64': 8, 'u64': 8,
         'f64': 8, 'double': 8}
SITE = re.compile(rf'\*\s*\(\s*&\s*(?P<sym>{IDENT})\s*\+\s*\(')
SCALE = re.compile(r'^(?P<expr>.+?)\s*(?P<op>\*|<<)\s*(?P<k>\d+)\s*$', re.S)


def _type(sym, text):
    hit = re.search(rf'\bextern\s+(?:const\s+)?(?P<t>{"|".join(SIZES)})\s+{re.escape(sym)}\s*;', text)
    return hit['t'] if hit else None


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    element, cast = [], []
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
        step = k if scale['op'] == '*' else 1 << k
        if step > SIZES[kind] or step & (step - 1):
            continue
        end = stop + tail.end()
        expr = scale['expr'].strip()
        if step == SIZES[kind]:
            index = expr if re.fullmatch(r'\w+', expr) else f'({expr})'
            element.append((site.start(), end, f'*(&{site["sym"]} + {index})'))
        cast.append((site.start(), end, f'*({kind} *)((s8 *)&{site["sym"]} + ({expr} {scale["op"]} {scale["k"]}))'))
    return [(FAMILY, edit(source, found)) for found in (element, cast) if found]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}
