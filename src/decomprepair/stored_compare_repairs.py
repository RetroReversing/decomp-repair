"""A condition that compares a value just stored, written to compare the stored memory instead of the temporary.

m2c keeps a computed value in a temporary and stores it, then tests the temporary:

    t = a + f();
    *(u32 *) (p + 0x2E) = t;
    if ((a < x && t < x) || (x < a && x < t)) ...

GCC 2.7.2's `fold_truth_andor` joins two simple comparisons of locals into one non-short-circuit AND (`sltu; sltu;
and`), and the target kept the two branches (`sltu; beqz; sltu; bnez`) because its second operand was a memory
reference, which is not a simple operand. Testing the memory the temporary was just stored to (`*(u32 *) (p + 0x2E) <
x`; cse still forwards the stored register, so no load is added) keeps the branches. Measured: 5910 -> 4405 on a
719-instruction N64 function (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`), after a `volatile` local that had given
the same branches by accident was dropped. A candidate rewrite; the exact judge decides.
"""
import re

from .integer_repair_support import view
from .line_scan import apply, lines, mentions

FAMILY = 'stored_value_compare'
FAMILIES = (FAMILY,)
_SET = re.compile(r'(?P<t>[A-Za-z_]\w*) = [^;]*;')
_STORE = re.compile(r'(?P<mem>\*\(.*\)) = (?P<t>[A-Za-z_]\w*);')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body = lines(part, source)
    out = []
    for i in range(len(body) - 2):
        first, store, test = body[i], body[i + 1], body[i + 2]
        made, stored = _SET.fullmatch(first.stripped), _STORE.fullmatch(store.stripped)
        if not made or not stored or made['t'] != stored['t'] or not test.stripped.startswith('if ('):
            continue
        t = made['t']
        if not mentions(test.text, t) or mentions(stored['mem'], t):
            continue
        memory = '(' + stored['mem'] + ')'
        text = re.sub(rf'(?<![\w.>]){re.escape(t)}\b', lambda _m, memory=memory: memory, test.source)
        out.append((FAMILY, apply(source, [(test.start, test.start + len(test.source), text)])))
    return out
