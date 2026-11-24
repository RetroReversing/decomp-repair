"""A run of scalar updates at a loop body's end, wrapped in one-shot scopes that change what their registers weigh.

GCC 2.x weighs every reference to a pseudo by its loop depth (flow.c), and global.c hands registers out in the order
`floor_log2(refs) * refs / live_length`. A `do { ... } while (0)` counts as a depth there and costs no instruction, so
the references inside it weigh one more each. `loop_weight_scope` (loop_weight_repairs) wraps a lone `x += y` or
`x++` among the function's last updates; a 681-instruction N64 bit-stream decoder (KMC GCC 2.7.2 `-O2`) needed three
shapes it never writes:

    do { do { do { off += 4; } while (0); } while (0); } while (0);   a constant step, three deep
    do { off += 4; c++; q3++; } while (0);                            a middle loop's whole run of steps
    i++; do { k++; t6 = *lim; } while (0); } while (t6 >= i);         the step with the exit test's load

The loop-made pointers that follow a counter are incremented right after it, so wrapping `k++` weighs them too. A
scope's loop notes are also a scheduling barrier for the second scheduler: wrapping `k++` alone put one pointer's
`addiu` before the exit test's load (the target has it after), and taking the load into the same scope (through a
local the test reads) restored the order. Each wrapper moved one pair of registers to the target's (the decoder went
from 65 to 0 with them and nothing else changed).

Children, for each run of one to three consecutive updates of plain locals (`x++`, `++x`, `x--`, `x += N`, `x -= N`,
`x += y`) that ends a block: the run wrapped at depth one, two and three, longest run first. A run made of a single
`++`/`+= 1` update is left to `loop_weight_scope`. The text is the same program: nothing but whole statements moves
into a scope with no branch or label. The candidate is never a verdict: the judge decides.
"""
import re

from .integer_repair_support import IDENT, INTEGER, NUMBER, edit, view

FAMILY = 'update_run_scope'
FAMILIES = (FAMILY,)
LIMIT = 12
_UPDATE = re.compile(
    rf'\s*(?:\+\+(?P<pre>{IDENT})|(?P<post>{IDENT})\s*(?:\+\+|--)|(?P<add>{IDENT})\s*[-+]=\s*(?P<rhs>{NUMBER}|{IDENT}))\s*;')


def _updates(part, names):
    """The update statements of plain locals, as (start, end, variable, plain_step)."""
    found = []
    for hit in re.finditer(r'(?<=[;{}])', part.clean[:part.end - 1]):
        if hit.start() <= part.opening:
            continue
        m = _UPDATE.match(part.clean, hit.start())
        if not m:
            continue
        var = m['pre'] or m['post'] or m['add']
        if var not in names:
            continue
        plain = m['add'] is None or m['rhs'] == '1'
        found.append((m.start(), m.end(), var, plain))
    return found


def _locals(part):
    """Scalars and pointers the function declares (a parameter too), whose address it never takes."""
    head = part.clean[:part.opening]
    params = head[head.rfind('(') + 1:]
    names = set()
    for text in (params, part.body):
        for m in re.finditer(rf'\b(?:{INTEGER}|void)\b\s*((?:\*\s*)*)({IDENT})\s*(?=[;=,)])', text):
            names.add(m.group(2))
    return {n for n in names if not re.search(rf'&\s*{n}\b', part.body)}


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|volatile)\b', part.body) or '__repair_update_run' in source:
        return []
    names = _locals(part)
    updates = _updates(part, names)
    runs = []
    for i in range(len(updates)):
        for length in (3, 2, 1):
            run = updates[i:i + length]
            if len(run) < length:
                continue
            if any(re.search(r'\S', part.clean[a[1]:b[0]]) for a, b in zip(run, run[1:])):
                continue
            if len({v for _, _, v, _ in run}) < length:
                continue
            if length == 1 and run[0][3]:
                continue
            start, end = run[0][0], run[-1][1]
            if not re.match(r'\s*}', part.clean[end:]):
                continue
            runs.append((length, start, end))
    runs.sort(key=lambda r: (-r[0], r[1]))
    out = []
    for _, start, end in runs:
        text = source[start:end].strip()
        lead = source[start:end][:len(source[start:end]) - len(source[start:end].lstrip())]
        for depth in (1, 2, 3):
            wrapped = lead + '/*__repair_update_run*/' + 'do { ' * depth + text + ' } while (0);' * depth
            out.append((FAMILY, edit(source, [(start, end, wrapped)])))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
