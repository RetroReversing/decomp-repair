"""A value computed from a local that dies there, written back into that local, as the game reused its variable.

KMC GCC 2.7.2 at `-O1`: `len = sqrtf(..); if (len > 15.0f) { s = 15.0f / len; v->x = s * v->x; .. }` has every
register of the comparison and the division swapped (the constant where the target has the length and back) and no copy
of the square root's result. Written `len = 15.0f / len; v->x = len * v->x;` it is exact (a controlled 830 -> 0 on one
function with two such blocks). `dead_scratch_reuse` renames whole integer locals and refuses a source local that the
stretch reads, which is this shape: the value is made *from* the local it takes over, and is a `float`.

consumed_value_reuse
    `X = E;` where `E` reads a local `Y` of `X`'s type, `Y` is not used again in the block (and is written before any
    read after it), and `X`'s reads after the statement all lie in that block. `X` is renamed to `Y` from the statement
    to the block's end. One child with every such site in the function renamed (two sibling blocks are usually the same
    source), then one per site. A declaration of `X` left without a use stays: it costs nothing and polishing drops it.

That the shared name gives global.c one pseudo where the source had two is a hypothesis read from the output.
"""
import re

from .c_scan import close, enclosing_block, header_before
from .guarded_loop_for import _written_before_read
from .integer_repair_support import IDENT, edit, view

FAMILY = 'consumed_value_reuse'
FAMILIES = (FAMILY,)
LIMIT = 12
_TYPE = r'(?:unsigned\s+(?:char|short|int)|signed\s+(?:char|short|int)|[su](?:8|16|32)|char|short|int|f32|f64|float|double)'
_DECLARATION = re.compile(rf'(?<![\w.])(?P<type>{_TYPE})\s+(?P<names>{IDENT}(?:\s*,\s*{IDENT})*)\s*;')
_ASSIGNMENT = re.compile(rf'(?<=[;{{}}])(?P<space>\s*)(?P<x>{IDENT})\s*=(?!=)(?P<value>[^;{{}}=]*(?:(?:==|!=|<=|>=)[^;{{}}=]*)*);')
_LOOP_HEADER = re.compile(r'^(?:for|while|do)\b')


def _uses(clean, name, low, high):
    return [(low + m.start(), low + m.end()) for m in re.finditer(rf'(?<![\w.]){re.escape(name)}\b', clean[low:high])
            if not clean[low:low + m.start()].rstrip().endswith('->')]


def _sites(clean, opening, end):
    """[[(start, end, new name)]]: the renames of every assignment that can take over a local it consumes."""
    low = opening + 1
    types = {}
    for decl in _DECLARATION.finditer(clean, low, end):
        for local in re.findall(IDENT, decl['names']):
            types[local] = re.sub(r'\s+', ' ', decl['type'])
    if re.search(r'\b(?:goto|volatile|asm|__asm__)\b', clean[low:end]):
        return []
    sites = []
    for m in _ASSIGNMENT.finditer(clean, opening, end):
        x = m['x']
        if x not in types or re.search(rf'&\s*{re.escape(x)}\b', clean[low:end]):
            continue
        start, after = m.start('x'), m.end()
        block = enclosing_block(clean, start, low)
        if block < 0:
            continue
        stop = close(clean, block)
        if stop < 0:
            continue
        for y in dict.fromkeys(re.findall(IDENT, m['value'])):
            if y == x or types.get(y) != types[x] or re.search(rf'&\s*{re.escape(y)}\b', clean[low:end]):
                continue
            if _uses(clean, y, after, stop) or not _uses(clean, x, after, stop):
                continue
            if not _written_before_read(clean, stop, low, end, y) or not _written_before_read(clean, stop, low, end, x):
                continue
            outer, looped = block, False
            while outer >= 0:
                if _LOOP_HEADER.match(header_before(clean, outer)):
                    looped = True
                outer = enclosing_block(clean, outer, low)
            if looped:
                continue
            sites.append([(a, b, y) for a, b in [(start, start + len(x))] + _uses(clean, x, after, stop)])
            break
    return sites


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    sites = _sites(part.clean, part.opening, part.end)
    if not sites:
        return []
    out = []
    if len(sites) > 1:
        together, taken = [], set()
        for site in sites:
            if not taken & {a for a, _, _ in site}:
                together += site
                taken |= {a for a, _, _ in site}
        out.append((FAMILY, edit(source, together)))
    out += [(FAMILY, edit(source, site)) for site in sites]
    return list(dict.fromkeys(item for item in out if item[1] != source))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 93}
