"""A sign-extending return written as m2c's shift pair, written as the cast it is.

m2c spells `return (s16) x;` for an `s16` function as a scratch local assigned `v = x << 0x10;` (once per path that
reaches the return) and `return v >> 0x10;`. The scratch holds a second copy of the value for the allocator and gives the
epilogue a shift pair where the original had one cast (gcc-2.7.2-kmc, `-O2`: `return (s16) var_a0;` with the scratch and
its assignments deleted took a 20-row accumulate-loop difference to 0 together with `accumulate_separate_dest`; the
scaffolding alone does not change the rows after the accumulate is fixed, so the pair is also offered combined there).
Offered when every assignment of the scratch is `v = X << 0x10;` or `<< 0x18` (the same X) and its only other use is
`return v >> N;`: those become `return (s16) X;` (`(s8)` for 0x18), the assignments and the declaration go. A candidate;
the exact judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'shift_pair_return_cast'
FAMILIES = (FAMILY,)
CAST = {'0x10': 's16', '16': 's16', '0x18': 's8', '24': 's8'}


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    for ret in re.finditer(rf'(?<![\w])return\s+(?P<v>{IDENT})\s*>>\s*(?P<n>0x10|16|0x18|24)\s*;', clean[:part.end]):
        if ret.start() < part.opening:
            continue
        scratch, shift = ret['v'], ret['n']
        assigns = list(re.finditer(rf'[ \t]*(?<![\w.>]){re.escape(scratch)}\s*=\s*(?P<x>{IDENT})\s*<<\s*{shift}\s*;[ \t]*\n?',
                                   clean[part.opening:part.end]))
        if not assigns or len({a['x'] for a in assigns}) != 1:
            continue
        uses = len(re.findall(rf'(?<![\w.>]){re.escape(scratch)}\b', clean[part.opening:part.end]))
        decl = re.search(rf'[ \t]*[A-Za-z_][\w ]*?\b{re.escape(scratch)}\s*;[ \t]*\n', clean[part.opening:part.end])
        if not decl or uses != len(assigns) + 2:
            continue
        x = assigns[0]['x']
        edits = [(part.opening + a.start(), part.opening + a.end(), '') for a in assigns]
        edits.append((part.opening + decl.start(), part.opening + decl.end(), ''))
        edits.append((ret.start(), ret.end(), f'return ({CAST[shift]}) {x};'))
        result = edit(source, edits)
        if result != source:
            out.append((FAMILY, result))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 90}
