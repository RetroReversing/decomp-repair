"""The setup statements right before a loop, in every other order (pointer and scalar copies, one-shot starts).

The assignments a loop's setup is made of (`p = &buf;`, `i = 0;`, `q = r;`, a one-shot `do { i = 0; } while (0);`) are
independent, and GCC 2.7.2 keeps the order of the ones it cannot reorder: the first scheduler leaves the pseudo
definitions as the C wrote them (the hoisted loop invariants follow them), so their order is the order of the
definitions the register allocator measures live ranges from, and of the instructions around the loop head. m2c
writes them in the target's address order; the game's source need not have. A KMC N64 function (`-G0 -mips3 -mgp32
-mfp32 -O2 -fno-strength-reduce`, 731 instructions) went 519 -> 459 with `var_a1 = temp;` moved from first to last of
four such statements, which put the target's moves and its spill reload in the target's order.

`pure_preheader_order` only permutes integer or function-address expressions; this one takes the pointer-to-local
(`p = &sp120;`), the copy of another local and the literal start, wrapped or not, and is the only one that reorders a
`/*__repair_loop_weight*/` start with its neighbours. Offered for a run of two to five such statements ending at a `do {`,
none reading what another one assigns, each variable assigned once. Each other order is a candidate; the judge decides.
"""
import itertools
import re

from .integer_repair_support import IDENT, NUMBER, view
from .line_scan import lines

FAMILY = 'preheader_run_order'
FAMILIES = (FAMILY,)
LIMIT = 24
_SIMPLE = re.compile(rf'(?P<indent>[ \t]*)(?:/\*__repair_loop_weight\*/)?(?:do \{{ )?(?P<lhs>{IDENT}) = (?P<rhs>&?{IDENT}|-?{NUMBER}); ?(?:\}} while \(0\);)?[ \t]*$')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body = lines(part, source)
    result = []
    for index, line in enumerate(body):
        if not re.match(r'[ \t]*do\s*\{[ \t]*$', line.text):
            continue
        run = []
        for back in range(index - 1, -1, -1):
            hit = _SIMPLE.fullmatch(body[back].source)
            if not hit or hit['indent'] != re.match(r'[ \t]*', line.text)[0]:
                break
            run.insert(0, (body[back], hit))
        run = run[-5:]
        if len(run) < 2:
            continue
        lhs = [hit['lhs'] for _, hit in run]
        rhs = {re.sub('^&', '', hit['rhs']) for _, hit in run}
        if len(set(lhs)) != len(lhs) or rhs & set(lhs):
            continue
        original = [row.source + '\n' for row, _ in run]
        start, end = run[0][0].start, run[-1][0].end
        if source[start:end] != ''.join(original):
            continue
        for order in itertools.permutations(range(len(run))):
            if list(order) == sorted(order):
                continue
            result.append((FAMILY, source[:start] + ''.join(original[i] for i in order) + source[end:]))
            if len(result) >= LIMIT:
                return result
    return result
