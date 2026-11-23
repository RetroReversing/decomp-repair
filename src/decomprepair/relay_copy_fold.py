"""A value copied through a local that nothing reads afterwards: `v = e; w = v;` written `w = e;`.

m2c keeps the register the target computed a value in (`var_s1 = limit & 0xFFFF;`) and copies it to the name the later
code uses (`temp_s2 = var_s1;`), and the register's later uses are all fresh assignments (`var_s1 = 0;`). The copy is
an insn of its own that the scheduler can place in the delay slot of the branch that follows (where the target has a
store), and it gives the relay a second live range that competes for a saved register. `variants` finds two statements
in a row, `v = e;` and `w = v;` (e free of calls, `v` and `w` locals), where every later occurrence of `v` in the function is
an assignment to it before any read, and writes `w = e;`: one child per such pair. Measured with the member-store step on
a 370-instruction function (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`): 1610 -> 1565; alone it was worse (1675 ->
1720), which is why it belongs in a chain with the store that fills the slot. The judge decides each child.
"""
import re

from .integer_repair_support import IDENT, INTEGER, _address_taken, edit, view

FAMILY = 'relay_copy_fold'
FAMILIES = (FAMILY,)
LIMIT = 6
PAIR = re.compile(rf'(?:(?<=[;{{}}])|^)(?P<lead>[ \t]*)(?P<v>{IDENT})\s*=\s*(?P<e>[^;{{}}=]+?)\s*;(?P<gap>\s*)(?P<w>{IDENT})\s*=\s*(?P=v)\s*;', re.M)


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|volatile|goto)\b', part.body):
        return []
    local = {m[1] for m in re.finditer(rf'(?<![\w*])(?:{INTEGER})\s+({IDENT})\s*[;=,]', part.clean[part.opening:part.end])}
    local = {n for n in local if not _address_taken(part.body, n)}
    results = []
    for pair in PAIR.finditer(part.clean, part.opening, part.end):
        v, w, e = pair['v'], pair['w'], pair['e']
        if v == w or v not in local or w not in local or re.search(rf'(?<![\w.>]){IDENT}\s*\(|\+\+|--', e) \
                or re.search(rf'(?<![\w.>]){re.escape(w)}\b', e):
            continue
        rest = part.clean[pair.end():part.end]
        later = re.search(rf'(?<![\w.>]){re.escape(v)}\b', rest)
        if later and not re.match(r'\s*=(?!=)', rest[later.end():]):
            continue
        text = edit(source, [(pair.start('v'), pair.end(), f'{w} = {source[pair.start("e"):pair.end("e")]};')])
        if text != source and (FAMILY, text) not in results:
            results.append((FAMILY, text))
        if len(results) >= LIMIT:
            break
    return results


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 80}  # the registry: no caller wiring (registry.py)
