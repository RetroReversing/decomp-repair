"""A pointer derived from the walking pointer, recomputed at the loop's tail: its definition moved to the loop's head.

m2c writes two pointers that walk a table together (a record and one of its fields) as the walking pointer's step and
then the derived pointer's recomputation at the end of the body, with the first value computed before the loop:

    sp = base + 0xC2;
    do {
        ...
        base += 0x1A0;
        sp = base + 0xC2;
    } while (...);

GCC's loop pass reduces a derived address (a "giv") only when it is set once per iteration before its uses; set at
the tail and used before that, it stays a plain recomputation (`addiu $s1,$s5,0xC2` after the step). The target of a
function with a voice table (KMC GCC 2.7.2) had the reduced pair, `addiu $s1,$s1,0x1A0` beside `addiu $s5,$s5,0x1A0`.
The definition written once at the head of the body, with the tail's recomputation gone, gives it:

    do {
        sp = base + 0xC2;
        ...
        base += 0x1A0;
    } while (...);

Measured on a 719-instruction N64 function (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`): 830 -> 605 together with
the other edits of its chain, the rows of the loop's tail and head gone. A candidate rewrite; the exact judge decides.
"""
import re

from .integer_repair_support import view
from .line_scan import apply, lines, loops

FAMILY = 'loop_head_pointer_giv'
FAMILIES = (FAMILY,)
_DERIVED = re.compile(r'(?P<y>[A-Za-z_]\w*) = (?P<x>[A-Za-z_]\w*) \+ (?P<k>(?:0[xX][0-9A-Fa-f]+|\d+));\s*')
_STEP = re.compile(r'(?P<x>[A-Za-z_]\w*) \+= (?:0[xX][0-9A-Fa-f]+|\d+);\s*')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body = lines(part, source)
    out = []
    for do, opening, closing, _ in loops(body):
        if do == 0 or closing - opening < 3:
            continue
        before, tail, step = body[do - 1], body[closing - 1], body[closing - 2]
        derived = _DERIVED.fullmatch(tail.stripped)
        walked = _STEP.fullmatch(step.stripped)
        if not derived or not walked or before.stripped != tail.stripped or walked['x'] != derived['x']:
            continue
        first = body[opening + 1]
        head = first.indent + tail.stripped + '\n'
        # the derived pointer must not be read between the loop's head and the tail's recomputation by a later set
        edits = [(before.start, before.end, ''), (body[opening].end, body[opening].end, head), (tail.start, tail.end, '')]
        out.append((FAMILY, apply(source, edits)))
    return out
