"""A masked field compared with a small constant, read through a halfword cast so the compare is the signed one.

`((word >> 2) & 7) < 2` on a halfword read the compiler types as unsigned (`u16`) came out `sltiu`; the target has
`slti`. A cast of the whole masked value to `s16`, `(s16) (((x >> 2) & 7)) < 2`, costs no instruction (the mask keeps
the value inside the halfword) and the comparison is signed: 4060 -> 3860 in a 970-instruction N64 state-machine
handler (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`), where the masked halfword came from a table read behind a
call. `field_extract_signed_cast` offers `(s32)` for a shift-then-mask written with one nesting level of parentheses
and never for an operand that holds a call; `(s32)` was a no-op here (the same bytes as no cast), `(s16)` was not.

`variants` finds each parenthesised `(... & K)` with K at most 0xFFFF directly left of a relational operator and a
literal, with the operand balanced however deeply it nests, and offers it wrapped in `(s16)`: one child per site, one
with all of them, at most 4 children. A candidate rewrite: the exact judge decides.
"""
import re

from .integer_repair_support import view

FAMILY = 'masked_compare_signed_cast'
FAMILIES = (FAMILY,)
LIMIT = 4
SITE = re.compile(r'&\s*(?P<mask>0[xX][0-9A-Fa-f]+|\d+)\s*\)\s*(?P<op><=|>=|<|>)(?![<>=])\s*(?:0[xX][0-9A-Fa-f]+|\d+)[uU]?\b')


def _open_of(clean, close):
    depth = 0
    for index in range(close, -1, -1):
        depth += (clean[index] == ')') - (clean[index] == '(')
        if depth == 0:
            return index
    return None


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    sites = []
    for hit in SITE.finditer(part.clean, part.opening, part.end):
        if int(hit['mask'], 0) > 0xFFFF:
            continue
        close = hit.end('mask') + part.clean[hit.end('mask'):hit.end('mask') + 40].index(')')
        start = _open_of(part.clean, close)
        if start is None or re.search(r'\(\s*(?:s8|s16|s32|u32|int)\s*\)\s*$', part.clean[:start]):
            continue
        sites.append((start, close + 1))
    out = [source[:start] + '(s16) ' + source[start:end] + source[end:] for start, end in sites]
    if len(sites) > 1:
        text = source
        for start, end in reversed(sites):
            text = text[:start] + '(s16) ' + text[start:end] + text[end:]
        out.append(text)
    return [(FAMILY, text) for text in dict.fromkeys(out)][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
