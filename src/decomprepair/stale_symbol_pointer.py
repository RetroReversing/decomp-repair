"""A pointer local m2c read on a path where it was never set to that array, written as the array itself.

m2c names a register once, so a pointer it saw set to a global array in one arm can be read in a later block that the
arm does not enclose:

    if (done) { ptr = sCounts; *((u8 *) (((char *) ptr) + 0)) -= 1; }
    ...
    if (gone) { *((u8 *) (((char *) ptr) + 1)) -= 1; }      /* ptr holds something else here */

The target forms the array's address again at the second place; the C that reads the local keeps the pointer in a saved
register across the calls between the two (a wider frame, `$s2`). A 133-instruction KMC-era N64 object update
(sn-n64-281 GCC 2.8.1) went 1086 -> 695 with the two places written as `sCounts[0]`, `sCounts[1]`, and on to 0 with two
more steps. The byte element must be written as a subscript: `((u8 *) sCounts)[1]` folds into `%lo(sCounts+1)` where
the target keeps `lui; addiu` and `lbu 1(reg)` (550 against 0).

The shape: a pointer local assigned `P = ARRAY;` where `ARRAY` is declared `extern T ARRAY[];`, and a read
`*((U *) (((char *) P) + K))` that stands after the assignment but outside the block that holds it, with no other
assignment of `P` in between. `stale_symbol_pointer` writes every such read of the web as the array and drops the
assignment when nothing else reads it; `stale_symbol_pointer_read` rewrites only the reads outside the block.
The judge decides every child.
"""
import re

from .arm_block_support import IDENT, brace_pairs
from .integer_repair_support import edit, view

FAMILY = 'stale_symbol_pointer'
FAMILY_READ = 'stale_symbol_pointer_read'
FAMILIES = (FAMILY, FAMILY_READ)
LIMIT = 6
_SIZES = {'char': 1, 's8': 1, 'u8': 1, 's16': 2, 'u16': 2, 's32': 4, 'u32': 4, 'int': 4}


def _arrays(clean):
    """{name: element type} for `extern T NAME[];` declarations."""
    return {m['name']: m['type'] for m in
            re.finditer(rf'\bextern\s+(?P<type>{IDENT})\s+(?P<name>{IDENT})\s*\[\s*\w*\s*\]\s*;', clean)}


def _block(blocks, at):
    """The innermost brace pair holding `at`."""
    best = None
    for opening, closing in blocks:
        if opening < at < closing and (best is None or opening > best[0]):
            best = (opening, closing)
    return best


def _access(array, element, cast, offset):
    size, wanted = _SIZES.get(element), _SIZES.get(cast)
    if size and wanted == size and offset % size == 0:
        text = f'{array}[{offset // size}]'
        return text if element == cast or size == 1 else f'(({cast} *) {array})[{offset // size}]'
    if wanted and offset % wanted == 0:
        return f'(({cast} *) {array})[{offset // wanted}]'
    return f'*(({cast} *) (((char *) {array}) + {offset}))'


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, lo, hi = part.clean, part.opening, part.end
    arrays = _arrays(clean)
    if not arrays:
        return []
    body = clean[lo:hi]
    pairs = brace_pairs(clean, lo, hi)
    if pairs is None:
        return []
    blocks = list(pairs.items())
    out = []
    assigned = re.finditer(rf'(?<![\w.>])(?P<local>{IDENT})\s*=\s*(?P<array>{IDENT})\s*;', body)
    for hit in assigned:
        local, array = hit['local'], hit['array']
        if array not in arrays or local in arrays or not re.search(rf'\*\s*{re.escape(local)}\s*[;,]', body):
            continue
        start, end = lo + hit.start('local'), lo + hit.end()
        home = _block(blocks, start)
        if home is None:
            continue
        again = re.compile(rf'(?<![\w.>*])\b{re.escape(local)}\s*=(?!=)').search(clean, end, hi)
        stop = again.start() if again else hi
        read = re.compile(
            rf'\*\s*\(\s*\(\s*(?P<cast>{IDENT})\s*\*\s*\)\s*\(\s*\(\s*\(\s*(?:char|s8|u8)\s*\*\s*\)\s*'
            rf'{re.escape(local)}\s*\)\s*\+\s*(?P<offset>0x[0-9A-Fa-f]+|\d+)\s*\)\s*\)')
        reads = list(read.finditer(clean, end, stop))
        stale = [r for r in reads if r.start() > home[1]]
        if not stale:
            continue
        element = arrays[array]
        rewrite = {r.start(): (r.start(), r.end(), _access(array, element, r['cast'], int(r['offset'], 0)))
                   for r in reads}
        uses = len(re.findall(rf'(?<![\w.>])\b{re.escape(local)}\b', clean[end:stop]))
        edits = list(rewrite.values())
        if uses == len(reads):
            edits.append((start, end, ''))
        out.append((FAMILY, edit(source, edits)))
        out.append((FAMILY_READ, edit(source, [rewrite[r.start()] for r in stale])))
    seen, unique = {source}, []
    for family, child in out:
        if child not in seen:
            seen.add(child)
            unique.append((family, child))
    return unique[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
