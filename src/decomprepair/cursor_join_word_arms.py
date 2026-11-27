"""A display-list command's second word that m2c moved to a join, written back into each arm through that arm's pointer.

Where every arm of an `if` or `switch` ends in the same `sw $v0, 4($v1)` after loading its own value, m2c prints the
store once, after the arms, through the global cursor:

    t = *gfx; *gfx = t + 8; *(s32 *)t = 0x06000000; v = &D_a;      (in every arm)
    ...
    *(u8 **)((u8 *)(*gfx) + 4) = v;                               (after them)

By then `*gfx` is the next command, so the target's `4($v1)` (the old pointer) is not what this writes. The game stored
in each arm (`gSPDisplayList((*gfx)++, D_a)`), and the compiler cross-jumped the stores. Measured on a KMC gcc 2.7.2
(`-O1`) mode switch: with `switch_if_chain`, `switch_tail_arm_order`, `default_neighbour_case` and
`merge_disjoint_temporaries` the draft reached 205, and this took it to 0.

cursor_join_word_arms
    Every `v = X;` becomes the store `T + N` = X through the pointer `T` that took the command before it (`T = *C;
    *C = T + K;`, N below K), and the joined stores are removed. Only when `v` is read nowhere else and each assignment
    has such a pointer since the store before it. One child per `v`.

The exact judge decides; the draft's own meaning is not kept, the target's store is.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'cursor_join_word_arms'
FAMILIES = (FAMILY,)
LIMIT = 4
_STORE = re.compile(rf'(?P<lhs>\*\s*\(\s*[\w ]+\*+\s*\)\s*\(\s*\(\s*[\w ]+\*\s*\)\s*)\(?\s*\*\s*(?P<cursor>{IDENT})'
                    rf'\s*\)?\s*(?P<offset>\+\s*(?P<at>\d+|0x[0-9a-fA-F]+)\s*\))\s*=\s*(?P<value>{IDENT})\s*;')
_TAKEN = re.compile(rf'(?<![\w.>*])(?P<local>{IDENT})\s*=\s*\*\s*(?P<cursor>{IDENT})\s*;(?:\s*do\s*\{{)?\s*\*\s*(?P=cursor)'
                    rf'\s*=\s*(?P=local)\s*\+\s*(?P<size>\d+|0x[0-9a-fA-F]+)\s*;')


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    stores = {}
    for hit in _STORE.finditer(part.clean, part.opening + 1, part.end):
        stores.setdefault(hit['value'], []).append(hit)
    children = []
    for value, joined in stores.items():
        writes = list(re.finditer(rf'(?<![\w.>*]){value}\s*=(?!=)\s*(?P<rhs>[^;]+);', part.clean[:part.end]))
        writes = [w for w in writes if w.start() > part.opening]
        uses = len(re.findall(rf'(?<![\w.>]){value}\b', part.body))
        declared = len(re.findall(rf'\*\s*{value}\s*;|\b[su](?:8|16|32)\s+{value}\s*;', part.body))
        if len(writes) < 2 or uses != len(writes) + len(joined) + declared:
            continue
        changes = [(hit.start(), hit.end(), '') for hit in joined]
        for write in writes:
            after = [hit for hit in joined if hit.start() > write.start()]
            if not after:
                break
            store = after[0]
            floor = max([hit.end() for hit in joined if hit.end() <= write.start()], default=part.opening)
            taken = [t for t in _TAKEN.finditer(part.clean, floor, write.start()) if t['cursor'] == store['cursor']]
            if not taken or int(store['at'], 0) >= int(taken[-1]['size'], 0):
                break
            lhs = source[store.start('lhs'):store.end('lhs')]
            offset = source[store.start('offset'):store.end('offset')]
            right = source[write.start('rhs'):write.end('rhs')]
            changes.append((write.start(), write.end(), f'{lhs}{taken[-1]["local"]} {offset} = {right};'))
        else:
            children.append((FAMILY, edit(source, changes)))
    return children[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
