"""A store put between a member's store and the statement that reads that member back.

`a->x = v; b->y = a->x;` lets cse forward the stored value to the read (no second load). The target's loads the member again:
the game stored another member in between (`a->z = 0.0f;`), and cse drops what it knows about memory at a store it cannot
prove disjoint, so the read-back is a real load. m2c lists the stores in the order of the stores' addresses, with the
other member's store before the one that is read back. A KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) player-update
routine of 1137 instructions went 1225 -> 745 with one statement moved (`... + 0x44 = 0.0f;` from before `... + 0x40 = angle;`
to between that store and the `+ 0x90` store that reads `+ 0x40` back): the missing `lwc1` and the register and order rows
after it all came right. Hypothesis from the match: cse's invalidation at a store through the same base.

readback_store_barrier
    Three consecutive one-line statements in one block: `L0` a store (`lhs0 = rhs0;`, no call), `L1` a store `lhs1 = rhs1;`
    and `L2` a statement that reads `lhs1` (its exact text) on its right-hand side, where `lhs0` appears in neither
    `L1` nor `L2` and `lhs1` does not appear in `L0`: one child writes `L1, L0, L2`. At most 6 children."""
import re

from .csource import _blank, find

FAMILY = 'readback_store_barrier'
FAMILIES = (FAMILY,)
LIMIT = 6
_STORE = re.compile(r'^(?P<indent>[ \t]*)(?P<lhs>[^;{}=\n]*?[^;{}=!<>\s][^;{}=\n]*?)\s*=(?!=)\s*(?P<rhs>[^;{}\n]+);[ \t]*$')
_CALL = re.compile(r'\b[A-Za-z_]\w*\s*\(')
_COMPOUND = re.compile(r'[-+*/%&|^<>!]$')


def _store(line):
    found = _STORE.match(line)
    if not found or _COMPOUND.search(found['lhs'].rstrip()) or re.match(r'\s*(?:return|if|while|for|else)\b', line):
        return None
    return found


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    lines = source[span[0]:span[1]].split('\n')
    cleans = clean[span[0]:span[1]].split('\n')
    out = []
    for i in range(len(lines) - 2):
        a, b, c = (_store(cleans[i + k]) for k in range(3))
        if not (a and b and c) or _CALL.search(a['rhs']) or _CALL.search(b['rhs']):
            continue
        indents = {a['indent'], b['indent'], c['indent']}
        lhs0, lhs1 = a['lhs'].strip(), b['lhs'].strip()
        if len(indents) != 1 or lhs0 == lhs1 or lhs1 not in c['rhs'] or lhs1 in a['rhs'] or lhs1 in lhs0 or lhs0 in lhs1:
            continue
        if lhs0 in b['rhs'] or lhs0 in c['rhs'] or lhs0 in c['lhs'] or lhs0 in b['lhs']:
            continue
        moved = lines[:i] + [lines[i + 1], lines[i], lines[i + 2]] + lines[i + 3:]
        out.append(source[:span[0]] + '\n'.join(moved) + source[span[1]:])
    return [(FAMILY, text) for text in dict.fromkeys(out)][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
