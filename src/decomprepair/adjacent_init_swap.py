"""Two neighbouring initialised locals written in the other order (GCC 2.7.2, KMC, N64).

`void *a = NULL; void *b = NULL;` at the top of a loop body is two `move rN,$zero` insns in the order written, and the
order is the start of each local's live range: global.c ranks a pseudo by `floor_log2 (refs) * refs / live length`, and
the live length is counted from the first insn that sets it. Two locals whose references are equal (both set to NULL,
one of them chosen by a flag, then read through) differ only in that length, so the one declared first, with the longer
range, ranks lower, and the other takes the lower-numbered of the registers they compete for. Swapping the two lines
gave the registers of the target for a pair of table pointers (a 16-bit and an 8-bit index walk) in a 529-instruction
function, 405 -> 360 with nothing else changed; no instruction is added or removed, so the search that scored the lines
in the original order saw only a register swap.

Each pair of adjacent declarations of the shape `T *x = 0;`, `T x = NULL;`, `T x = 1;` (a literal start, so neither
refers to the other), or m2c's plain `x = NULL;` (two globals cleared at entry: their stores' order in a
1337-instruction collision sweep, 6300 -> 6260), is offered swapped. A candidate rewrite; the exact judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .line_scan import lines

FAMILY = 'adjacent_init_swap'
FAMILIES = (FAMILY,)
MAX_CHILDREN = 8
# A type and its name are apart (a space or a `*`); m2c's split form, a plain `x = 0;`, has no type. Without the
# separator the pattern split one name in two (`gPlayerActo` + `r`), and two names ending in one letter looked equal.
_DECL = re.compile(rf'^(?P<type>(?:(?:unsigned|signed|struct|const)\s+)*{IDENT}(?:\s+|\s*\*[\s*]*))?'
                   rf'(?P<name>{IDENT})\s*=\s*(?P<value>NULL|0|-?\d+|0[xX][0-9a-fA-F]+)\s*;$')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    found = [line for line in lines(part, source)]
    out = []
    for first, second in zip(found, found[1:]):
        a, b = _DECL.match(first.stripped), _DECL.match(second.stripped)
        if not a or not b or first.indent != second.indent or a['name'] == b['name']:
            continue
        if first.end != second.start:
            continue
        swapped = second.source + '\n' + first.source + '\n'
        text = edit(source, [(first.start, second.end, swapped)])
        if text != source:
            out.append((FAMILY, text))
        if len(out) >= MAX_CHILDREN:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
