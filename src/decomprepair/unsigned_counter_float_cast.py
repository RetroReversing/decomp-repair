"""An unsigned counter converted to a float: the signed conversion the target's `cvt.s.w` shows.

m2c types a loop counter that is compared with `sltu` as `u32` and writes its conversion to a float as `(f32) var_t4`.
gcc 2.7.2 converts an unsigned operand with a test of its top bit and a bias (`cvt.d.w`, `bltz`, `add.d` with 2^32) and
the game's code has none of that: its counter was a signed variable in the conversion (`(f32) (s32) x`) whatever its
compares were. In a tile-rectangle builder the unsigned conversion cost a branch and a constant load in the loop and the
register order after them (8832 -> 6765 on a 315-instruction function, the rest of the match still to find).

`variants` takes every `(f32) V`, `(f64) V`, `(float) V`, `(double) V` whose operand `V` is a plain local or parameter
declared `u32`, `unsigned`, `unsigned int` or `unsigned long` (not already cast, not a call or a member) and writes
`(T) (s32) V`. One proposal with every site, one per variable (at most 6). The compare's own signedness is not touched.
A hypothesis; the exact judge decides."""
import re

from .integer_repair_support import edit, view

FAMILY = 'unsigned_counter_float_cast'
FAMILIES = (FAMILY,)
LIMIT = 6

_ID = r'[A-Za-z_]\w*'
_UNSIGNED = r'(?:u32|unsigned(?:\s+(?:int|long))?)'
_CONVERSION = re.compile(rf'\(\s*(?P<type>f32|f64|float|double)\s*\)\s*(?P<v>{_ID})\b(?!\s*[(\[.]|\s*->)')


def _unsigned_names(clean, opening, end):
    names = set()
    for hit in re.finditer(rf'(?<![\w])(?:register\s+)?{_UNSIGNED}\s+(?P<n>{_ID})\s*[;,)=]', clean[:end]):
        names.add(hit['n'])
    return names


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    unsigned = _unsigned_names(part.clean, part.opening, part.end)
    sites = {}
    for hit in _CONVERSION.finditer(part.clean, part.opening, part.end):
        if hit['v'] in unsigned:
            sites.setdefault(hit['v'], []).append(hit)
    if not sites:
        return []
    names = list(sites)[:LIMIT]
    out = []
    groups = [names] if len(names) > 1 else []
    groups += [[n] for n in names]
    for group in groups:
        edits = [(h.start('v'), h.start('v'), '(s32) ') for n in group for h in sites[n]]
        out.append((FAMILY, edit(source, edits)))
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 99}  # the registry: no caller wiring (registry.py)
