"""A `do { } while (0)` scope that holds a label or a `goto` that crosses it, taken off so a pseudo weighs less.

GCC 2.x counts every reference inside a `do { } while (0)` once per loop depth when it ranks pseudos for the saved
registers (flow.c, `floor_log2(uses) * uses / live_length` in global.c; hypothesis, read from the allocation dumps of one
function). The existing unwrap families (`weight_scope_unwrap`, `one_shot_unwrap`, `operation_scope_unwrap`) only take
off a wrapper whose gotos and labels all lie inside it, because a goto into or out of it looked unsafe. A `goto` never
cares what braces it crosses, so the only things that can change meaning are a `break`/`continue` that the wrapper
catches, a `switch`, and a declaration that would escape the block (the braces stay, so it cannot).

Found by hand on a KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) 67-instruction search over 4-byte records written as a
`goto` loop: the scan loop's head (`entry = base; scan: ...; id = ...;`) sat in a wrapper that a `goto scan` jumped into
from the loop's tail and a `goto advance` left. That wrapper doubled the weight of the threshold compared inside it, so
the threshold (5 weighted references over 21 insns) outranked the loop limit (4 over 18) and took the lower saved
register; the target has them the other way round. Taking the wrapper off (not one line of the instructions changes)
brought the function from 20 to 0, and no family could reach it from there: every wrapper that holds a label was
skipped.

`variants(source, name)` gives one variant per such wrapper and one with all of them off. Hypotheses for the exact
judge, never equivalence claims."""
import re

from .allocation_weight_combination import _unwrap_edit, _wrappers
from .integer_repair_support import IDENT, edit, view

FAMILIES = ('crossing_scope_unwrap',)
LIMIT = 6
_LABEL = rf'(?:^|[;{{}}])\s*({IDENT})\s*:(?!:)'
_DECLARATION = r'(?:^|[;{}])\s*(?:const\s+|volatile\s+|unsigned\s+|signed\s+)*[A-Za-z_]\w*[ \t]+\**\s*\w+\s*(?:=[^;]*)?;'
_DECLARED_TYPES = r'(?:s32|u32|u16|s16|u8|s8|f32|f64|int|char|short|long|float|double|void)'


def _crossing(clean, wrapper):
    """The wrapper's text when it holds a label or a goto and nothing that its removal could change; else None."""
    body = clean[wrapper[1]+1:wrapper[2]-1]
    labels = set(re.findall(_LABEL, body)) - {'default', 'case'}
    if not labels and not re.search(r'\bgoto\b', body):
        return None
    if re.search(r'\b(?:break|continue|switch|case|default)\b', body):
        return None
    if re.search(rf'(?:^|[;{{}}])\s*(?:{_DECLARED_TYPES})\b[^;{{}}()]*;', body):
        return None
    return body


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    groups = [_unwrap_edit(w) for w in _wrappers(clean, part.opening+1, part.end-1) if _crossing(clean, w) is not None]
    if not groups:
        return []
    result = [(FAMILIES[0], edit(source, group)) for group in groups[:LIMIT]]
    if len(groups) > 1:
        result.append((FAMILIES[0], edit(source, [e for group in groups for e in group])))
    seen, out = set(), []
    for family, text in result:
        if text != source and text not in seen:
            seen.add(text)
            out.append((family, text))
    return out
