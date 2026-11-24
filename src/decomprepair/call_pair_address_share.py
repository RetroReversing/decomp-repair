"""call_pair_address_share: `&local` handed to two calls in a row, read through one pointer local all such pairs share.

m2c writes each address argument as it finds it:

    segmentClosestPoint(&edgeA, v0, v1, p);  da = distanceSquared3D(&edgeA, p);
    segmentClosestPoint(&edgeB, v1, v2, p);  db = distanceSquared3D(&edgeB, p);

A KMC-compiled N64 collision routine (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`, 2,267 instructions) computes each
address once into a saved register and passes it to both calls (`addiu $s0, $sp, 0xF0; move $a0, $s0; jal ...;
move $a0, $s0; jal ...`, then `addiu $s0, $sp, 0x100` for the next pair). One pointer local set before each pair,
the same local at every site, was 12757 -> 7266 and shrank the frame 0x2A0 -> 0x290: the shared local has enough
references to win a saved register, where m2c's spelling leaves cse a pseudo per address that reload spills. One local
per pair was worse (13360), so the child that shares one local across all pairs comes first; a child per pair follows.

A pair is two consecutive statements, each with one call whose first argument is the same `&X` of a local (array or
scalar). The rewrite writes `P = &X;` before the first and `P` for those first arguments."""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'call_pair_address_share'
FAMILIES = (FAMILY,)
LOCAL = '__repair_point'
LIMIT = 6

IDENT = r'[A-Za-z_]\w*'


def _statements(clean, lo, hi):
    """(start, end) of each simple statement ending in `;` between lo and hi, at any nesting (not `for` headers)."""
    out = []
    start = None
    depth = 0
    i = lo
    while i < hi:
        c = clean[i]
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
        elif depth == 0 and c in '{}':
            start = None
        elif depth == 0 and c == ';':
            if start is not None:
                out.append((start, i + 1))
            start = None
        elif start is None and not c.isspace() and depth == 0:
            start = i
        i += 1
    return out


def _local_type(body, name):
    m = re.search(rf'(?m)^[ \t]*(?:volatile\s+)?({IDENT}(?:\s+{IDENT})?)\s*(\**)\s*(?<!\w){name}\s*(\[[^\]]*\])?\s*;', body)
    if not m:
        return None
    base, stars = m[1], m[2]
    if base in ('return', 'goto', 'else'):
        return None
    return f'{base} {stars}*'


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or LOCAL in clean:
        return []
    body = clean[opening:end]
    statements = _statements(clean, opening + 1, end - 1)
    pairs = []
    for (a0, a1), (b0, b1) in zip(statements, statements[1:]):
        first, second = clean[a0:a1], clean[b0:b1]
        if clean[a1:b0].strip() or re.match(r'\s*(?:if|while|for|switch|return|goto)\b', first + ' ' + second):
            continue
        if len(re.findall(rf'\b{IDENT}\s*\(', first)) != 1 or len(re.findall(rf'\b{IDENT}\s*\(', second)) != 1:
            continue
        # the address both calls take first (an output point and the query point it is measured from: the first)
        lead = re.search(rf'\b{IDENT}\s*\(\s*&\s*({IDENT})\b(?!\s*[\[.(]|\s*->)', first)
        again = re.search(rf'\b{IDENT}\s*\(\s*&\s*({IDENT})\b(?!\s*[\[.(]|\s*->)', second)
        shared = [lead[1]] if lead and again and lead[1] == again[1] else []
        if len(shared) != 1:
            continue
        x = shared[0]
        kind = _local_type(body, x)
        alias = re.search(rf'(?m)^[ \t]*#\s*define\s+{x}\s+({IDENT})\s*\[', source)
        if not kind and alias:
            # a search's `#define spF0 local_spF0[0]` names one element of a local array
            kind = _local_type(body, alias[1])
        if not kind:
            continue
        pairs.append((a0, b1, x, kind))
    if not pairs:
        return []
    kinds = {k for *_, k in pairs}

    def rewrite(chosen, local):
        text = source
        for a0, b1, x, _ in sorted(chosen, reverse=True):
            run = re.sub(rf'(?<=\()\s*&\s*{x}\b(?!\s*[\[.(]|\s*->)', local, text[a0:b1])
            text = text[:a0] + f'{local} = &{x}; ' + run + text[b1:]
        return text

    def declare(text, local, kind):
        at = text.find('{', find(text, name)[0]) + 1
        return text[:at] + f'\n    {kind}{local};' + text[at:]

    out = []
    if len(kinds) == 1 and len(pairs) > 1:
        kind = next(iter(kinds))
        out.append((FAMILY, declare(rewrite(pairs, LOCAL), LOCAL, kind)))
    for pair in pairs[:LIMIT]:
        out.append((FAMILY, declare(rewrite([pair], LOCAL), LOCAL, pair[3])))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 96}  # the registry: no caller wiring (registry.py)
