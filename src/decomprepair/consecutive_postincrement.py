"""Reads of `p[0]`, `p[1]`, ... followed by `p += n;`, written as the post-incremented cursor the game read with.

    out->end = e[0];                 out->end = *e++;
    out->attr = e[1];        ->      out->attr = *e++;
    e += 2;

GCC keeps one cursor stepped between the loads (`lw; addiu; lw; addiu`) for the post-increments; the indexed form
reads both through one base and steps once, with other registers. A table copy loop: 920 -> 0 (SN64 GCC 2.8.1 -O2).
The same for stores (`e[0] = a; e[1] = b; e += 2;`). The statements must be adjacent, cover every index from 0 in
order, and name the cursor nowhere else. The exact judge decides.
"""
import re

from .integer_repair_support import IDENT, _address_taken, edit, view

FAMILY = 'consecutive_postincrement'
FAMILIES = (FAMILY,)
_STEP = re.compile(rf'(?<=;)\s*(?:(?P<name>{IDENT})\s*\+=\s*(?P<count>\d+)|(?P<again>{IDENT})\s*=\s*(?P=again)\s*\+\s*'
                   rf'(?P<more>\d+)|(?P<one>{IDENT})\+\+)\s*;')
LIMIT = 8


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    for step in _STEP.finditer(clean, part.opening, part.end):
        cursor = step['name'] or step['again'] or step['one']
        count = int(step['count'] or step['more'] or 1)
        if not 1 <= count <= 8 or _address_taken(part.body, cursor):
            continue
        end = step.start()
        accesses = []
        for index in range(count - 1, -1, -1):
            semicolon = end - 1
            if clean[semicolon] != ';':
                break
            start = max(clean.rfind(c, part.opening, semicolon) for c in ';{}') + 1
            statement = clean[start:semicolon]
            access = rf'\b{cursor}\s*\[\s*{index}\s*\]' + (rf'|\*\s*{cursor}\b(?!\s*(?:\+\+|--|\[))' if index == 0 else '')
            hits = list(re.finditer(access, statement))
            plain = re.fullmatch(r'\s*[^=]*[^-+*/%&|^<>=!]=(?!=)[^=]*', statement)
            if len(hits) != 1 or not plain or len(re.findall(rf'\b{cursor}\b', statement)) != 1:
                break
            accesses.append((start + hits[0].start(), start + hits[0].end()))
            end = start
        if len(accesses) != count:
            continue
        changes = [(a, b, f'*{cursor}++') for a, b in accesses]
        changes.append((step.start(), step.end(), ''))
        out.append((FAMILY, edit(source, changes)))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
