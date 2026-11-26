"""Two locals that hold the same value in different arms of one switch, `case 4: r = w & 0x1F; ... case 5: r_b1 = w &
0x1F; ...`, written as one variable.

The game's arms often came from one macro or one copied block, so a value both arms compute (the low vertex index of a
triangle command) was one variable; a rewrite that names it per arm gives two short pseudos where the game had one
global one. One variable lives in both arms, conflicts with what each arm keeps in `$v0`/`$v1` and is coloured by
global.c as one allocno, which moves it off the register the arm's copy had (`andi $a0, $v0, 0x1f` for the target's
low index, where the private local was tied to the copy in `$v0`). An SN GCC 2.8.1 model loader (sn-n64-281, 618
instructions), its gSP1Triangle and gSP2Triangles arms: 410 -> 365 (360 -> 315 under `-mfp32`), both triangle arms then
matching. `disjoint_local_merge` merges a local into the nearest earlier one that is never live with it, which here was
another variable (485); the same-value signal finds the pair. Which pairs the game shared is decided by the judge.

`variants` looks at each switch: two integer locals of one declared type, each mentioned only inside its own arms
(`case`/`default` segments that end in `break;` or `return`), first mentioned in every segment by a plain assignment,
and each assigned the same expression somewhere (`a = E;` and `b = E;` with `E` the same text). The later-declared one
is renamed to the other and its declaration dropped. One child per pair.
"""
import re

from . import c_scan
from .integer_repair_support import IDENT, INTEGER, _address_taken, edit, view

FAMILY = 'arm_role_local_merge'
FAMILIES = (FAMILY,)
LIMIT = 6
LABEL = re.compile(r'\b(?:case\b[^;{}]*?[^:]:(?!:)|default\s*:)')


def _segments(clean, opening, close):
    """The top-level case segments of a switch body: (start, end) spans, nested switches' labels skipped."""
    labels = [hit for hit in LABEL.finditer(clean, opening + 1, close)
              if c_scan.enclosing_block(clean, hit.start(), opening) == opening]
    return [(hit.end(), after.start() if after else close) for hit, after in zip(labels, labels[1:] + [None])]


def _first_is_set(clean, lo, hi, v):
    first = re.search(rf'\b{v}\b', clean[lo:hi])
    if not first:
        return True
    at = lo + first.start()
    if not re.search(r'[;{}:]\s*$', clean[:at]):
        return False
    set_ = re.match(rf'{v}\s*=(?!=)\s*(?P<e>[^;]*);', clean[at:hi])
    return bool(set_) and not re.search(rf'\b{v}\b', set_['e'])


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|goto)\b', part.body):
        return []
    clean, results = part.clean, []
    decls = {m['v']: (m['t'], m.start(), m.end()) for m in re.finditer(
        rf'(?m)^[ \t]*(?P<t>{INTEGER})\s+(?P<v>{IDENT})\s*;[ \t]*\n?', clean[part.opening:part.end])}
    for switch in re.finditer(r'\bswitch\s*\(', clean[part.opening:part.end]):
        start = part.opening + switch.end() - 1
        header = c_scan.close(clean, start, '(', ')')
        body = re.match(r'\s*{', clean[header + 1:part.end]) if header > 0 else None
        if not body:
            continue
        opening = header + 1 + body.end() - 1
        close = c_scan.close(clean, opening)
        segments = _segments(clean, opening, close)
        ends = {seg: bool(re.search(r'\b(?:break|return\b[^;]*)\s*;\s*}?\s*$', clean[seg[0]:seg[1]])) for seg in segments}
        where = {}
        for v in decls:
            uses = [m.start() for m in re.finditer(rf'\b{v}\b', clean[part.opening:part.end])]
            uses = [part.opening + u for u in uses if part.opening + u > part.opening + decls[v][2] - 1]
            segs = {seg for seg in segments for u in uses if seg[0] <= u < seg[1]}
            if (uses and all(any(seg[0] <= u < seg[1] for seg in segs) for u in uses) and all(ends[s] for s in segs)
                    and all(_first_is_set(clean, *s, v) for s in segs) and not _address_taken(part.body, v)):
                where[v] = segs
        names = sorted(where, key=lambda v: decls[v][1])
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                if decls[a][0] != decls[b][0] or where[a] & where[b]:
                    continue
                values_a = {re.sub(r'\s+', ' ', m['e'].strip()) for m in
                            re.finditer(rf'(?<![\w.>]){a}\s*=(?!=)\s*(?P<e>[^;]*);', clean[opening:close])}
                values_b = {re.sub(r'\s+', ' ', m['e'].strip()) for m in
                            re.finditer(rf'(?<![\w.>]){b}\s*=(?!=)\s*(?P<e>[^;]*);', clean[opening:close])}
                if not values_a & values_b:
                    continue
                _, lo, hi = decls[b]
                edits = [(part.opening + lo, part.opening + hi, '')]
                edits += [(opening + m.start(), opening + m.end(), a)
                          for m in re.finditer(rf'\b{b}\b', clean[opening:close])]
                text = edit(source, tuple(edits))
                if (FAMILY, text) not in results:
                    results.append((FAMILY, text))
                if len(results) >= LIMIT:
                    return results
    return results


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 700}  # the registry: no caller wiring (registry.py)
