"""Two pointer locals that take turns, written as one variable.

m2c names each pointer it recovers: the element a loop loads and tests, then the object it picks from two arms. GCC 2.7
makes one pseudo of a source variable, and the allocator ranks the pseudos by `floor_log2(uses) * uses / live length`:
two names are two pseudos with half the uses each, one name is a single pseudo whose uses add up and whose ranges are
joined. The target gave the element and the picked object the same register (`lw $v0,($s2); beqz $v0 ...; lw $v0,
LO($v0); lw $s0,0x6c($v0)`), where two pseudos took `$a0` and `$v0` (a 180-instruction N64 function, `gcc-2.7.2-kmc
-G0 -mips3 -mgp32 -mfp32 -O2`: 285 -> 270 with the second pointer written as the first, then the last mismatch went
with `loop_constant_stage`). `disjoint_local_merge` only knows integer locals and drops a pair that sits in one loop
body, which is where two pointers take turns.

Two locals declared with the same pointer type, neither's address taken, are merged when the first mention of each is
an assignment and every mention of the first comes before every mention of the second (an earlier value is never read
by the second's uses; a loop that carries a pointer round to its next pass is left alone because the first mention is
then not an assignment). The later local's mentions become the earlier one's and its declaration goes. Nearest pairs
first. A candidate for the exact judge, never a verdict."""
import re

from .integer_repair_support import IDENT, view
from .line_scan import apply

FAMILIES = ('pointer_local_merge',)
LIMIT = 8
GENERIC = re.compile(r'[ \t]*[A-Za-z_][\w \t*]*[\w\]](?:\s*\[[^\]]*\])?\s*;[ \t]*')
DECL = re.compile(rf'(?m)^[ \t]*(?P<type>(?:{IDENT}[ \t]+)*{IDENT}[ \t]*\*+)[ \t]*(?P<name>{IDENT})[ \t]*;[ \t]*\n')


def _mentions(clean, name, start, end):
    return [m for m in re.finditer(rf'(?<![\w.>]){re.escape(name)}\b', clean[start:end])]


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    start, end = part.opening + 1, part.end - 1
    decls = []
    at = clean.find('\n', start) + 1
    while at < end:
        line_end = clean.find('\n', at)
        line = clean[at:line_end]
        if line.strip() and not GENERIC.fullmatch(line):
            break
        m = DECL.match(clean, at)
        if m:
            decls.append(m)
        at = line_end + 1
    if len(decls) < 2:
        return []
    body_start = at
    info = {}
    for d in decls:
        if re.search(r'\b(?:volatile|register)\b', d['type']) or re.search(rf'&\s*{re.escape(d["name"])}\b', clean[body_start:end]):
            continue
        hits = _mentions(clean, d['name'], body_start, end)
        if not hits or not re.match(r'\s*=(?!=)', clean[body_start + hits[0].end():end]):
            continue
        info[d['name']] = (d, body_start + hits[0].start(), body_start + hits[-1].start())
    ranked = []
    for a, (da, _, last_a) in info.items():
        for b, (db, first_b, _) in info.items():
            if a != b and ' '.join(da['type'].split()) == ' '.join(db['type'].split()) and last_a < first_b:
                ranked.append((first_b - last_a, a, b))
    out = []
    for _, a, b in sorted(ranked)[:LIMIT]:
        db = info[b][0]
        edits = [(db.start(), db.end(), '')]
        edits += [(body_start + m.start(), body_start + m.end(), a) for m in _mentions(clean, b, body_start, end)]
        out.append((FAMILIES[0], apply(source, edits)))
    return out
