"""A word local that is only returned, declared as narrow as the function's return type.

m2c types the local that collects a result `s32` and converts it at the end (`return (s8) var;`, or a shift pair). The
game often declared it as the return type. It matters beyond the return: while the local is a word like the loop counter
it is copied from (`pos = i;`), cse treats the two as one value and later uses of the counter read the copy; a local of
another width is another machine mode, so the counter keeps its own register for the stores that follow. On a
129-instruction N64 table insertion (SN64 GCC 2.8.1, `-G0 -mips3 -O2`) narrowing `s32 pos` to the function's `s8` was
140 -> 0, and 360 -> 220 from the clean rewrite. The cse explanation is a hypothesis from the diff, not read in cse.c.

A word function whose returns are `return (s8) var;` (what `shift_pair_return_cast` makes of m2c's shift pair) counts
the cast's width, and then every read must be that cast.

Only a local whose every read is `return X;` (or a cast of it to the return type) qualifies, so the narrowing cannot
change what the function returns. Children: each such local retyped, one at a time.
"""
import re

from .integer_repair_support import _address_taken, edit, view

FAMILY = 'result_local_narrow_return'
FAMILIES = (FAMILY,)
LIMIT = 4
_NARROW = r'(?:s8|u8|s16|u16|signed\s+char|unsigned\s+char|char|unsigned\s+short|short)'
_WIDE = r'(?:s32|u32|unsigned\s+int|signed\s+int|int)'
# writes whose low bits depend only on the low bits of the operands, so a narrower local gives the same narrow result
_WRITE = re.compile(r'\s*(?:[+\-*|&^]?=(?!=)|\+\+|--)')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body = part.clean[part.opening:part.end]
    returns = re.search(rf'\b(?P<type>{_NARROW})\s+{re.escape(name)}\s*\([^(){{}};]*\)\s*$', part.clean[:part.opening])
    # a word function that casts what it returns says the width too: m2c's `s32 f()` ending in `return (s8) var;`
    casts = {hit['type'] for hit in re.finditer(rf'\breturn\s*\(\s*(?P<type>{_NARROW})\s*\)\s*[A-Za-z_]\w*\s*;', body)}
    if not returns and len(casts) != 1:
        return []
    narrow = returns['type'] if returns else casts.pop()
    out = []
    for decl in re.finditer(rf'(?<=[;{{}}])\s*(?P<type>{_WIDE})\s+(?P<name>[A-Za-z_]\w*)\s*(?=[;=])', body):
        local = decl['name']
        if _address_taken(body, local) or not _only_returned(body, local, narrow, decl.start('name'), bool(returns)):
            continue
        at = part.opening + decl.start('type')
        out.append((FAMILY, edit(source, [(at, part.opening + decl.end('type'), narrow)])))
        if len(out) >= LIMIT:
            break
    return out


def _only_returned(body, local, narrow, declared, narrow_function):
    """Whether every mention of `local` after its declaration is a write statement or a `return` of it."""
    returned = False
    for hit in re.finditer(rf'(?<![\w.])(?<!->){re.escape(local)}\b', body):
        if hit.start() == declared:
            continue
        before = body[:hit.start()].rstrip()
        # without a narrow return type only the cast keeps the value what it was
        cast = rf'(?:\(\s*{re.escape(narrow)}\s*\)\s*){"?" if narrow_function else ""}'
        if re.search(rf'\breturn\s*{cast}\(?$', before) and re.match(r'\)?\s*;', body[hit.end():]):
            returned = True
            continue
        # a write that is a whole statement: an assignment used as a value would read the truncated local
        if before.endswith((';', '{', '}')) and _WRITE.match(body, hit.end()):
            continue
        return False
    return returned


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 40}
