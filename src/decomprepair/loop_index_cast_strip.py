"""A short loop's counter used as a subscript through a narrowing cast, written without it.

A search (or m2c) leaves `a[(unsigned short) i]` or `a[(unsigned short) ((unsigned char) i)]` in a loop that counts to a
small literal. The casts change nothing the program does and each is an extra `andi` or another register for gcc, and
`array_index_width` only adds them. On a 61-instruction KMC `-O1` copy routine, dropping both from one loop went 630 to
65 in one step.

The rewrite fires only where the cast cannot change the value: the loop is `for (i = 0; i < N; i++)` with a literal
`N <= 128`, which every narrow type holds, and the body never assigns `i` or takes its address. One child per loop, and
one with every loop.
"""
import re

from .arm_block_support import IDENT
from .integer_repair_support import NUMBER, edit, view
from .pattern_repairs import close

FAMILY = 'loop_index_cast_strip'
FAMILIES = (FAMILY,)

HEAD = re.compile(rf'\bfor\s*\(\s*(?P<i>{IDENT})\s*=\s*0\s*;\s*(?P=i)\s*<\s*(?P<n>{NUMBER})\s*;\s*'
                  rf'(?:(?P=i)\s*\+\+|\+\+\s*(?P=i)|(?P=i)\s*\+=\s*1)\s*\)\s*(?P<open>\{{)')
NARROW = r'(?:u8|s8|u16|s16|char|signed\s+char|unsigned\s+char|short|unsigned\s+short)'


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out, every = [], []
    for head in HEAD.finditer(clean, part.opening, part.end):
        index = head['i']
        if int(head['n'].rstrip('uUlL'), 0) > 128:
            continue
        end = close(clean, head.start('open'), '{', '}')
        if end is None or end < 0:
            continue
        body = clean[head.end():end]
        if re.search(rf'(?:\+\+|--|&)\s*{index}\b|\b{index}\s*(?:\+\+|--|(?:<<|>>|[-+*/%&|^])?=(?!=))', body):
            continue
        wrapped = (rf'\[\s*(?P<index>(?:\(\s*{NARROW}\s*\)\s*(?:\(\s*)?)+{index}(?:\s*\))*)\s*\]')
        edits = []
        for hit in re.finditer(wrapped, body):
            text = hit['index']
            if text.count('(') == text.count(')'):
                edits.append((head.end() + hit.start('index'), head.end() + hit.end('index'), index))
        if edits:
            text = edit(source, edits)
            if (FAMILY, text) not in out:
                out.append((FAMILY, text))
            every += [e for e in edits if e not in every]
    if every and len(out) > 1:
        text = edit(source, every)
        if (FAMILY, text) not in out:
            out.append((FAMILY, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 92}  # the registry: no caller wiring (registry.py)
