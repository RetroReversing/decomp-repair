"""The two arguments of an inline add helper passed the other way round, one call at a time.

m2c spells every `a + b` it could not fold as a call to a tiny inline helper (`inline_fn23(arg0, arg1)` returning
`arg0 + arg1`), and the order it wrote is the order it saw the operands in, not the order the game's expression had.
The compiler keeps the operand order of an add (`addu $a0,$v0,$s0` is not `addu $a0,$s0,$v0`), so each call whose
arguments are the wrong way round leaves one row of the difference. Swapping the arguments of one call (each passed
through a cast to the other parameter's type, so the program is still well typed and adds the same two values) moves
exactly that row: on a KMC `gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2` menu-update function five such calls each
removed one row of the difference (75 -> 10 together with the other repairs), and no repair offered them. A helper is a
function in the source whose body is `return a + b;` (or `b + a`) over its two parameters; a call is swapped at
the top-level of its argument list, and one child is offered per call. A candidate for the exact judge, never a verdict."""
import re

from .csource import _blank
from .integer_repair_support import edit
from .pattern_repairs import close

FAMILY = 'add_helper_operand_swap'
FAMILIES = (FAMILY,)
LIMIT = 8
HELPER = re.compile(
    r'(?:inline\s+static|static\s+inline|inline)\s+[\w\s*]+?\b(?P<name>[A-Za-z_]\w*)\s*'
    r'\(\s*(?P<t0>[\w\s*]+?)\s*(?P<a0>[A-Za-z_]\w*)\s*,\s*(?P<t1>[\w\s*]+?)\s*(?P<a1>[A-Za-z_]\w*)\s*\)\s*'
    r'\{\s*return\s+(?P<l>[A-Za-z_]\w*)\s*\+\s*(?P<r>[A-Za-z_]\w*)\s*;\s*\}')


def _helpers(clean):
    found = {}
    for m in HELPER.finditer(clean):
        if {m['l'], m['r']} == {m['a0'], m['a1']}:
            found[m['name']] = (m['t0'].strip(), m['t1'].strip(), m.start(), m.end())
    return found


def _arguments(clean, open_paren):
    """The (start, end) spans of the top-level arguments of the call whose `(` is at `open_paren`, or None."""
    end = close(clean, open_paren)
    if not end:
        return None
    spans, depth, begin = [], 0, open_paren + 1
    for at in range(open_paren + 1, end - 1):
        c = clean[at]
        if c in '([':
            depth += 1
        elif c in ')]':
            depth -= 1
        elif c == ',' and depth == 0:
            spans.append((begin, at))
            begin = at + 1
    spans.append((begin, end - 1))
    return spans, end


def variants(source, name, header=''):
    clean = _blank(source)
    helpers = _helpers(clean)
    if not helpers:
        return []
    out = []
    for helper, (t0, t1, hstart, hend) in helpers.items():
        for m in re.finditer(r'(?<![\w.>])' + re.escape(helper) + r'\s*\(', clean):
            if hstart <= m.start() < hend:
                continue
            found = _arguments(clean, m.end() - 1)
            if not found or len(found[0]) != 2:
                continue
            (a_start, a_end), (b_start, b_end) = found[0]
            first, second = source[a_start:a_end].strip(), source[b_start:b_end].strip()
            new_first = second if t0 == t1 else f'({t0}) ({second})'
            new_second = first if t0 == t1 else f'({t1}) ({first})'
            out.append(edit(source, [(a_start, b_end, f'{new_first}, {new_second}')]))
    return [(FAMILY, c) for c in dict.fromkeys(out) if c != source][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 130}
