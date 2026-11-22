"""A `do { } while (0)` that wraps the last cases of a `switch`, taken off (with the dead locals inside it).

A scheduling repair wrapped a switch's trailing cases in `do { case 1: ...; break; case 2: ...; } while (0);` so the
second scheduler would keep their order, and the case labels jump into the wrapper. It is legal C, and a `break` in
it leaves the wrapper and so the switch, but it adds one loop depth to every reference in those cases, which moves the
allocator's ranking for any local the cases and the code before them share. The crossing-scope family declines it (a
wrapper with `case` labels and a `break`: it cannot tell the `break` leaves the switch anyway). When the wrapper ends the
switch body, the `break`s mean the same with and without it, so it can come off; `{ long long phantom_wide = x; }`
blocks left in it by the padding repair go with it.

On a KMC (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`) 87-instruction N64 record-stream walker the wrapper was the
last of four edits (the byte local merged, the load scaled in two arms: 40 -> 0); alone it made the saved best worse
(130 -> 180), so it only pays after them, which is why the chain keeps it as a later step. Only a wrapper directly
followed by the `}` that closes a `switch` body, holding no `continue` and no declaration. A hypothesis for the exact
judge, not an equivalence claim."""
import re

from .allocation_weight_combination import _unwrap_edit, _wrappers
from .integer_repair_support import edit, view

FAMILY = 'switch_tail_scope_unwrap'
FAMILIES = (FAMILY,)
LIMIT = 4
_PADDING = re.compile(r'\{\s*(?:long\s+long|s64|u64)\s+phantom_\w+\s*=\s*[^;{}]*;\s*\}\s*')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    for wrapper in _wrappers(clean, part.opening+1, part.end-1)[:LIMIT]:
        body = clean[wrapper[1]+1:wrapper[2]-1]
        after = clean[wrapper[3]:part.end-1]
        if (not re.search(r'(?:^|[;{}\s])case\s+[^:;{}]+:', body) or re.search(r'\bcontinue\b', body)
                or not after.lstrip().startswith('}')
                or re.search(r'(?:^|[;{}])\s*(?:s32|u32|u16|s16|u8|s8|f32|f64|int|char|short|long|void)\b[^;{}()]*;', body)
                and not _PADDING.search(body)):
            continue
        # The brace must close a switch body: the nearest unclosed `{` before the wrapper opens `switch (...)`.
        depth, at = 0, wrapper[0]
        while at > part.opening and depth >= 0:
            at -= 1
            depth += (clean[at] == '}')-(clean[at] == '{')
        if not re.search(r'\bswitch\s*\([^{};]*\)\s*$', clean[:at].rstrip()):
            continue
        edits = _unwrap_edit(wrapper)
        for pad in _PADDING.finditer(clean, wrapper[1], wrapper[2]):
            edits.append((pad.start(), pad.end(), ''))
        text = edit(source, edits)
        if text != source:
            out.append((FAMILY, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 75}  # the registry: no caller wiring (registry.py)
