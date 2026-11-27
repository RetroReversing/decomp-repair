"""`(n - 1) + A` and `(n - 1) + B` in one block, written with `n` decremented once and added to each constant.

    t[2] = n - 1 + 0x80000000;       n--;
    t[6] = n - 1 + 0xA0000000;  ->   t[2] = n + 0x80000000;
                                     t[6] = n + 0xA0000000;

GCC folds `n - 1 + 0x80000000` into `n + 0x7FFFFFFF`; the target has the `addiu` of its own and two plain `lui; addu`.
A memory-size table update: 1465 -> 0 (SN64 GCC 2.8.1 -O2). Offered only outside loops, when two or more adjacent-block
uses share one `local - K` and the local's next mention afterwards (if any) is a plain assignment. The exact judge
decides.
"""
import re

from .integer_repair_support import edit, locals_for, view
from .pattern_repairs import close

FAMILY = 'shared_decrement_in_place'
FAMILIES = (FAMILY,)
_NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)[uU]?'
LIMIT = 4


def _loops(clean, opening, end):
    for hit in re.finditer(r'\b(?:for|while|do)\b', clean[opening:end]):
        at = opening + hit.end()
        if hit[0] != 'do':
            paren = clean.find('(', at)
            at = close(clean, paren, '(', ')') or at
        at = len(clean) - len(clean[at:].lstrip())
        stop = close(clean, at, '{', '}') if clean.startswith('{', at) else clean.find(';', at) + 1
        yield opening + hit.start(), stop or end


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\bgoto\b', part.body):
        return []
    clean = part.clean
    loops = list(_loops(clean, part.opening, part.end))
    out = []
    for decl in locals_for(part):
        local = decl['name']
        pattern = re.compile(rf'(?<![\w*/%.>-])\b{local}\s*-\s*(?P<k>{_NUMBER})\b\s*(?=\+\s*{_NUMBER}\s*;)')
        hits = list(pattern.finditer(clean, part.opening, part.end))
        if len(hits) < 2 or len({hit['k'] for hit in hits}) != 1:
            continue
        first, last = hits[0].start(), hits[-1].end()
        start = max(clean.rfind(c, part.opening, first) for c in ';{}') + 1
        stop = clean.find(';', last) + 1
        window = clean[start:stop]
        if ('{' in window or '}' in window or len(re.findall(rf'\b{local}\b', window)) != len(hits)
                or any(a <= first < b for a, b in loops)):
            continue
        later = re.search(rf'\b{local}\b', clean[stop:part.end])
        if later and not re.match(r'\s*=(?!=)', clean[stop + later.end():]):
            continue
        k = hits[0]['k']
        step = f'{local}--;' if int(k.rstrip('uU'), 0) == 1 else f'{local} -= {k};'
        first_line = len(clean) - len(clean[start:].lstrip())
        changes = [(first_line, first_line, step + '\n        ')]
        changes += [(hit.start(), hit.end(), local + ' ') for hit in hits]
        out.append((FAMILY, edit(source, changes)))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
