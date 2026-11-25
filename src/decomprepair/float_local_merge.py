"""Two float locals whose lives never overlap, written as one variable (singly and two merges at once).

`disjoint_local_merge` pairs integer locals only (`locals_for` reads `s32`-like declarations, one per line), so a float
function whose original reused its scalars never got the merge: a 438-instruction N64 floor-height ray test (sn-n64-281
GCC 2.8.1, `-G0 -mips3 -O2 -mgas -meb -mcpu=VR4300 -mhard-float -mfp32`) computes two plane distances `d1`, `d2` for the
ray's ends and, later in the same loop body, three edge distances `e0`, `e1`, `e2`. The target keeps `e1` in `d1`'s
register and `e2` in `d2`'s (`mov.s $f12, $f0` for the third distance, the first argument register `d2` prefers), which is
one pseudo per pair: written `d1 = ...` and `d2 = ...` for the edge distances, 1067 -> 532 (`e1` alone) -> 257 (both),
measured with the app's judge-worker. Both values are assigned before they are read in every iteration, so the merge
does not change the program.

`variants` reads the function's `f32`/`float`/`f64`/`double` locals (comma lists too; no initialisers, arrays, pointers
or address-taken names), and pairs an earlier local A with a later B of the same type when A's last mention comes before
B's first, B's first mention is a plain `B = ...;`, and, when both sit in one loop, A's first mention in that loop is a
plain assignment too and B is not named after the loop (so neither value is carried round it). One child per pair,
nearest first, then the pairs of two such merges with four different names. A hypothesis about the original's
variables; the judge decides."""
import itertools
import re

from .integer_repair_support import _address_taken, edit, view
from .pattern_repairs import close

FAMILY = 'float_local_merge'
FAMILIES = (FAMILY,)
SINGLES = 16
LIMIT = 40
FLOAT = r'(?:f32|f64|float|double)'
DECL = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<type>{FLOAT})[ \t]+(?P<names>[A-Za-z_]\w*(?:[ \t]*,[ \t]*[A-Za-z_]\w*)*)[ \t]*;[ \t]*$')
LOOP = re.compile(r'\b(?:for|while)\s*\(|\bdo\s*\{')


def _mentions(clean, name, start, end):
    return [start + m.start() for m in re.finditer(rf'(?<![\w.>]){re.escape(name)}\b', clean[start:end])]


def _plain_assignment(clean, at, name, lo):
    before = clean[lo:at].rstrip()
    if before and before[-1] not in ';{}:':
        return False
    statement = re.match(rf'{re.escape(name)}\s*=(?!=)([^;]*);', clean[at:])
    return bool(statement) and not re.search(rf'(?<![\w.>]){re.escape(name)}\b', statement.group(1))


def _loops(clean, lo, hi):
    spans = []
    for hit in LOOP.finditer(clean, lo, hi):
        if hit.group(0).startswith('do'):
            end = close(clean, hit.end() - 1, '{', '}')
        else:
            paren = close(clean, hit.end() - 1, '(', ')')
            block = re.match(r'\s*\{', clean[paren:hi]) if paren else None
            end = close(clean, paren + block.end() - 1, '{', '}') if block else None
        if end:
            spans.append((hit.start(), end))
    return spans


def _declarations(source, clean, lo, hi):
    found = {}
    for decl in DECL.finditer(clean, lo, hi):
        names = [n.strip() for n in decl['names'].split(',')]
        for name in names:
            found[name] = (decl['type'], decl, names)
    return found


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    lo, hi = part.opening + 1, part.end - 1
    decls = _declarations(source, clean, lo, hi)
    if len(decls) < 2:
        return []
    last_decl = max(d.end() for _t, d, _n in decls.values())
    loops = _loops(clean, last_decl, hi)
    use = {}
    for local in decls:
        hits = _mentions(clean, local, last_decl, hi)
        if hits and not _address_taken(clean[last_decl:hi], local):
            use[local] = hits
    order = sorted(use, key=lambda n: use[n][0])
    pairs = []
    for a, b in itertools.permutations(order, 2):
        if decls[a][0] != decls[b][0] or not use[a][-1] < use[b][0]:
            continue
        if not _plain_assignment(clean, use[b][0], b, lo):
            continue
        shared = [(s, e) for s, e in loops if s < use[a][-1] and use[b][0] < e]
        if shared:
            s, e = min(shared, key=lambda span: span[1] - span[0])
            inside = [m for m in use[a] if m > s]
            if not inside or not _plain_assignment(clean, inside[0], a, lo) or use[b][-1] > e:
                continue
        pairs.append((use[b][0] - use[a][-1], a, b))
    pairs.sort()
    chosen = pairs[:SINGLES]

    def child(merges):
        edits = []
        removed = {}
        for a, b in merges:
            _type, decl, names = decls[b]
            removed.setdefault(decl.start(), (decl, list(names)))[1].remove(b)
            edits += [(m, m + len(b), a) for m in use[b]]
        for decl, rest in removed.values():
            if rest:
                edits.append((decl.start('names'), decl.end('names'), ', '.join(rest)))
            else:
                end = decl.end() + (1 if source[decl.end():decl.end() + 1] == '\n' else 0)
                edits.append((decl.start(), end, ''))
        return edit(source, edits)

    out = [(FAMILY, child([(a, b)])) for _d, a, b in chosen]
    combos = sorted(((d1 + d2, (a1, b1), (a2, b2)) for (d1, a1, b1), (d2, a2, b2) in itertools.combinations(chosen, 2)
                     if len({a1, b1, a2, b2}) == 4), key=lambda item: item[0])
    out += [(FAMILY, child([first, second])) for _d, first, second in combos]
    return list(dict.fromkeys(out))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 900}  # the registry: no caller wiring (registry.py)
