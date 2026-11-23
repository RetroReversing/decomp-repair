"""m2c's comparison-result temporaries in an if/else-if chain, written as the chain's own comparisons.

For a chain that classifies two values by size (`w == 64 && h == 64`, `w == 32 && h == 128`, ...) m2c keeps each
comparison's result in a temporary the first time it is needed and reuses it in the later conditions of the chain:

    t1 = h == 0x40;
    if (t1 && (w == 0x40)) { ... } else { t2 = w == 0x20; if (t2 && (h == 0x80)) { ... } else if (t2 & t1) { ... } }

The source the game had is the plain chain, `(w == 0x40) && (h == 0x40)`, with the width compared first in every
condition. The temporaries are variables the first scheduler and global.c see (one pseudo each, live across arms), and
the two sides of each `&&` come in the order the temporaries happened to be needed, so the compares are issued in a
different order than the game's (`xori` pairs with their operands swapped, the results in other registers). Written
as the plain chain, cse shares the repeated compares itself, and on a texture-load builder of 715 instructions
(`gcc-2.7.2-kmc -O2 -G0 -mips3 -mgp32 -mfp32`) this and two scratch-local inlines took 1140 to 1060 (the rest of the
match came from other families, `docs/learnings/function/...`).

Offered where it is the same program: `T = V op K;` (T a local, V a plain identifier, K a literal), every later read of
T up to the end of its block or its next assignment is replaced by `(V op K)` when V is not assigned or addressed in
that range, and the assignment is dropped. Then, as a second child, the two comparisons of every `X && Y` / `X & Y`
condition over the same two variables are put in the order most of the chain's conditions have them (a strict
majority of at least three).

`variants` gives, labelled `compare_temp_cascade_inline`: every temporary inlined, and every temporary inlined with the
conditions' order aligned.
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'compare_temp_cascade_inline'
FAMILIES = (FAMILY,)
ID = r'[A-Za-z_]\w*'
NUM = r'-?(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*'
OP = r'==|!=|<=|>=|<|>'
ASSIGN = re.compile(rf'(?m)^[ \t]*(?P<t>{ID})\s*=\s*\(?\s*(?P<v>{ID})\s*(?P<op>{OP})\s*(?P<k>{NUM})\s*\)?\s*;[ \t]*\n')
TERM = rf'\(\s*{ID}\s*(?:{OP})\s*{NUM}\s*\)'
CONJ = re.compile(rf'\b(?P<kw>if)\s*\(\s*(?P<a>{TERM})\s*(?P<j>&&|&)\s*(?P<b>{TERM})\s*\)')


def _block_end(clean, at, limit):
    depth = 0
    for k in range(at, limit):
        c = clean[k]
        if c == '{':
            depth += 1
        elif c == '}':
            if depth == 0:
                return k
            depth -= 1
    return limit


def _inline(part, source):
    edits = []
    for hit in ASSIGN.finditer(part.clean, part.opening + 1, part.end):
        t, v = hit['t'], hit['v']
        if t == v or not re.search(rf'(?m)^[ \t]*[A-Za-z_][\w\s*]*\b{re.escape(t)}\s*;', part.clean):
            continue
        stop = _block_end(part.clean, hit.end(), part.end)
        again = re.compile(rf'(?<![\w.>]){re.escape(t)}\s*=(?!=)').search(part.clean, hit.end(), stop)
        if again:
            stop = again.start()
        reads = [m for m in re.finditer(rf'(?<![\w.>]){re.escape(t)}\b(?!\s*=(?!=))', part.clean[hit.end():stop])]
        rng = part.clean[hit.end():stop]
        if not reads or re.search(rf'(?<![\w.>])(?:{re.escape(v)}\s*(?:[-+*/&|^]?=(?!=)|\+\+|--)|&\s*{re.escape(v)}\b|\+\+\s*{re.escape(v)}|--\s*{re.escape(v)})', rng):
            continue
        text = f"({v} {hit['op']} {hit['k']})"
        edits.append((hit.start(), hit.end(), ''))
        for m in reads:
            edits.append((hit.end() + m.start(), hit.end() + m.end(), text))
    return edits


def _terms(text):
    m = re.match(rf'\(\s*({ID})\s*({OP})\s*({NUM})\s*\)', text)
    return m[1], m[2], m[3]


def _align(source, name):
    part = view(source, name)
    if not part:
        return source
    found = [m for m in CONJ.finditer(part.clean, part.opening + 1, part.end)
             if _terms(m['a'])[0] != _terms(m['b'])[0]]
    groups = {}
    for m in found:
        a, b = _terms(m['a'])[0], _terms(m['b'])[0]
        groups.setdefault(frozenset((a, b)), []).append(m)
    edits = []
    for hits in groups.values():
        if len(hits) < 3:
            continue
        orders = {}
        for m in hits:
            orders.setdefault((_terms(m['a'])[0], _terms(m['b'])[0]), []).append(m)
        if len(orders) != 2:
            continue
        (_, low), (_, high) = sorted(orders.items(), key=lambda kv: len(kv[1]))
        if len(low) == len(high):
            continue
        for m in low:
            edits.append((m.start('a'), m.end('b'), f"{m['b']} {m['j']} {m['a']}"))
    return edit(source, edits) if edits else source


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    edits = _inline(part, source)
    if not edits:
        return []
    inlined = edit(source, edits)
    out = [inlined]
    aligned = _align(inlined, name)
    if aligned != inlined:
        out.append(aligned)
    return [(FAMILY, c) for c in dict.fromkeys(out) if c != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 68}
