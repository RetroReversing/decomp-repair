"""A pointer loaded from a field and offset in one expression, written as a load into the local and an add to it
(GCC 2.7.2, KMC, N64).

m2c writes `p = ((u8 *) (*((void **) (((u8 *) rec) + 0x3C)))) + i * 6;`. The compiler expands that as two pseudos, the
loaded base and the sum, and local-alloc.c can tie the sum to the base only when the base's register dies in the add;
with the base a pseudo of its own that is read once the register the sum gets differs from the base's (`lw $v0,..;
addu $v1,$v0,$t1`), so the pointer takes a second register through the arms and the lifetimes of all that share
`$v0`/`$v1` move. Written as the game would have kept it, as two statements on the local itself,

    p = *((void **) (((u8 *) rec) + 0x3C));  p = ((u8 *) p) + i * 6;

the load goes straight into the local and the add reads and writes it (`lw $v1,..; addu $v1,$v1,$t1`). On a
529-instruction function the pair of arms that build two table pointers went from 360 to 340 with the edit in both
arms (350 and 405 with either alone: the arms share the registers their sums take, so one child offers all of them).

The assignment must have a cast of a load as the left operand of a `+` and the local must not occur in the rest of the
sum. A candidate rewrite; the exact judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'load_add_in_place'
EVERY = 'load_add_in_place_all'
FAMILIES = (FAMILY, EVERY)
MAX_CHILDREN = 8
_START = re.compile(rf'(?<![\w.>])(?P<v>{IDENT})\s*=\s*\(')
_CAST = re.compile(r'\s*\((?P<cast>[\w\s]+?[\s*]*\*)\s*\)\s*\(')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out, edits = [], []
    for hit in _START.finditer(clean, part.opening + 1, part.end):
        if clean[part.opening + 1:hit.start()].rstrip()[-1:] not in (';', '{', '}'):
            continue
        outer = close(clean, hit.end() - 1)
        if not outer:
            continue
        inner = clean[hit.end():outer - 1]
        cast = _CAST.match(inner)
        if not cast:
            continue
        load_open = hit.end() + cast.end() - 1
        load_end = close(clean, load_open)
        if not load_end or load_end != outer - 1:
            continue
        load = clean[load_open + 1:load_end - 1].strip()
        if not load.startswith('*'):
            continue
        tail = re.match(r'\s*\+\s*(?P<rest>[^;{}]+);', clean[outer:])
        if not tail or re.search(rf'(?<![\w.>]){re.escape(hit["v"])}\b', tail['rest']) \
                or re.search(rf'(?<![\w.>]){re.escape(hit["v"])}\b', load):
            continue
        v = hit['v']
        end = outer + tail.end()
        rest = source[outer + tail.start('rest'):outer + tail.end('rest')].strip()
        text = f"{v} = {source[hit.end() + cast.end():load_end - 1].strip()}; {v} = ({cast['cast'].strip()}) {v} + {rest};"
        edits.append((hit.start(), end, text))
        out.append((FAMILY, edit(source, [edits[-1]])))
        if len(edits) >= MAX_CHILDREN:
            break
    if len(edits) > 1:
        out.append((EVERY, edit(source, edits)))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
