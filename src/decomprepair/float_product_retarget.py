"""A float product written into the variable it multiplies, written into another float that is free there.

`d = call(...) * d;` with the result in the variable that is also an operand makes GCC 2.7.2 (KMC, `-G0 -mips3 -mgp32
-mfp32 -O2`) put that variable first: expand_binop swaps a commutative operation's operands so the destination is the
first one (`mul.s $f20,$f20,$f0`). The target has the call's result first (`mul.s $f20,$f0,$f20`), so its result went to
another variable: the original reused one float for the distance in both of the function's loops, where m2c split it
into `d` and `d_2` (a 445-instruction N64 target picker: the register stayed the target's `$f20`, the operand order
was the last differing row of its float code).

For a float local assigned `x = <expr with a call that reads x>;` the range from that assignment to the end of its block (its
value is read there and nowhere after: the next mention outside the block is an assignment, and the first mention in an
enclosing loop is one) is written through each other float local that is not mentioned in the range or in that loop,
and is never read after it. A candidate for the exact judge, never a verdict.
"""
import re

from .integer_repair_support import view
from .line_scan import apply, block_end, lines, mentions

FAMILY = 'float_product_retarget'
FAMILIES = (FAMILY,)
LIMIT = 6
SPAN = 14
_FLOAT = re.compile(r'(?m)^[ \t]*(?:f32|float)[ \t]+([A-Za-z_]\w*)[ \t]*;')


def _assigns(text, name):
    return re.match(rf'\s*{re.escape(name)}\s*(?:[-+*/]|)=(?!=)', text) is not None


def _enclosing(body, index):
    """The `{` line index around the line at `index` and the line index of its closing `}`, or None."""
    depth = 0
    for i in range(index, -1, -1):
        depth += body[i].text.count('}') - body[i].text.count('{')
        if depth < 0:
            return i, block_end(body, i)
    return None


def _loop_around(body, index):
    """(open, close) of the innermost `do { } while` around the line at `index`, or None."""
    probe = index
    while True:
        around = _enclosing(body, probe)
        if not around or around[1] is None:
            return None
        if around[0] > 0 and body[around[0] - 1].stripped == 'do':
            return around
        probe = around[0] - 1 if around[0] > 0 else -1
        if probe < 0:
            return None


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    floats = [hit[1] for hit in _FLOAT.finditer(part.clean[:part.end])]
    if len(floats) < 2:
        return []
    body = lines(part, source)
    result = []
    for index, line in enumerate(body):
        hit = re.match(r'([A-Za-z_]\w*)\s*=(?!=)\s*([^;]*);$', line.stripped)
        if not hit or hit[1] not in floats or not mentions(hit[2], hit[1]) or not re.search(r'\b\w+\s*\(', hit[2]) or '*' not in hit[2]:
            continue
        var = hit[1]
        around, loop = _enclosing(body, index), _loop_around(body, index)
        if not around or not loop or around[1] is None:
            continue
        # the value lives to the end of the block, or to the next assignment of `var` inside it
        end = next((k for k in range(index + 1, around[1]) if _assigns(body[k].stripped, var)), around[1])
        if end - index > SPAN:
            continue
        # `var` is set before it is read in every pass of the loop, and is not mentioned after the block in it
        first = next(b.stripped for b in body[loop[0]:loop[1] + 1] if mentions(b.stripped, var))
        if not _assigns(first, var) or (mentions(first.split('=', 1)[1], var) and first != line.stripped):
            continue
        if any(mentions(body[k].stripped, var) for k in range(end, loop[1] + 1) if k >= around[1] and k != index):
            continue
        after_var = next((k for k in range(loop[1] + 1, len(body)) if mentions(body[k].stripped, var)), None)
        if after_var is not None and not _assigns(body[after_var].stripped, var):
            continue
        inside = ' '.join(b.stripped for b in body[loop[0]:loop[1] + 1])
        for other in floats:
            if other == var or mentions(inside, other):
                continue
            after = next((k for k in range(loop[1] + 1, len(body)) if mentions(body[k].stripped, other)), None)
            if after is not None and not _assigns(body[after].stripped, other):
                continue
            edits = []
            for k in range(index, end):
                for found in re.finditer(rf'(?<![\w.>]){re.escape(var)}\b', body[k].text):
                    if k == index and found.start() > body[k].text.index('='):
                        continue  # the first line's right-hand side keeps reading the old value
                    edits.append((body[k].start + found.start(), body[k].start + found.end(), other))
            if edits:
                result.append((FAMILY, apply(source, edits)))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 100}  # the registry: no caller wiring (registry.py)
