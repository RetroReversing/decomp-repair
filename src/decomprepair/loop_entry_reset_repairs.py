"""A loop counter that is 0 on every path into a second loop but assigned only inside a conditional before it.

m2c writes the reset where the first loop ended (`if (n > 0) { do { ... i += 1; } while (i < n); i = 0; }`) and starts
the later loop that reuses `i` with only its own offset variable set (`o = 0; do { ... i += 1; o = i * 0x28; } while (i <
0x20);`). The compiler cannot see that `i` is 0 at the join (cse does not carry the value across it), so the second
loop's induction variable is computed from `i` at entry (`sll; addu; sll`) where the target's is `move $s0,$zero`
and the strength-reduced giv steps by one constant. Written `i = 0;` just before the later loop's initialisers, the
reduction sees a constant start. Measured on a 719-instruction N64 function (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32
-O2`): 2880 -> 2335. A candidate rewrite; the exact judge decides.
"""
import re

from .integer_repair_support import view
from .line_scan import apply, lines, loops

FAMILY = 'loop_entry_counter_reset'
FAMILIES = (FAMILY,)
_COUNTER = re.compile(r'while \((?P<c>[A-Za-z_]\w*) <')
_INIT = re.compile(r'[A-Za-z_]\w* = (?:-?(?:0[xX][0-9A-Fa-f]+|\d+)|[A-Za-z_]\w*);')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body = lines(part, source)
    out = []
    for do, opening, closing, loop_while in loops(body):
        hit = _COUNTER.match(body[loop_while].stripped)
        if not hit:
            continue
        counter = hit['c']
        if not any(re.fullmatch(rf'{counter} (?:\+= 1|= {counter} \+ 1);', l.stripped) for l in body[opening:closing]):
            continue
        first = do
        while first > 0 and _INIT.fullmatch(body[first - 1].stripped):
            first -= 1
        if any(re.match(rf'{counter} =(?!=)', body[k].stripped) for k in range(first, do)):
            continue
        # the counter must have been set to zero earlier, in a block of its own (the reset after its first loop)
        if not any(re.fullmatch(rf'{counter} = 0;', body[k].stripped) and len(body[k].indent) > len(body[do].indent)
                   for k in range(0, first)):
            continue
        out.append((FAMILY, apply(source, [(body[first].start, body[first].start, f'{body[do].indent}{counter} = 0;\n')])))
    return out
