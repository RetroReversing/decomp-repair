"""m2c's hand-reduced copy loop (guard, integer cursors, a bound local) written back as the indexed `for` loop.

m2c shows the loop pass's own work as source: a guard on the trip count, one integer variable per induction variable
the compiler made, each started in the guard and stepped beside the counter, and the bound the compiler hoisted held in
a local with a copy of itself:

    n = size >> 2;
    i = 0;
    if (n != 0) {
        n = n;
        dst = base & MASK;
        src = base;
        do {
            put((s32 *) dst, get(src));
            dst += 4;
            i += 1;
            src += 4;
        } while (i < n);
    }

The game wrote `for (i = 0; i < (size >> 2); i++) put((s32 *) ((base & MASK) + i * 4), get(base + i * 4));`. The
compiler then hoists the shift and the mask, makes the two stepped registers and copies the entry test's value into the
bound's register itself. Measured on one 63-instruction N64 copy routine (SN GCC 2.8.1, `-G0 -mips3 -O2`): the saved
best at 160; the three edits together 0. Apart they do not help: cursors alone 160, with the `for` loop 110, and the
`for` loop that keeps its stepped cursors 1096. So they are one child. Why the loop pass orders the registers this way
is not read from the compiler's source (hypothesis).

`integer_cursor_for_loop` writes the cursors as the counter's multiples (`stepped_induction_index`), the guarded loop
as a `for` (`counted_loop_shapes`) and the bound's expression in the test; `integer_cursor_for_loop_bound_local` keeps
the bound local, for a target that holds the bound in a register of the source's own. Offered only when every start the
rewrite repeats, whatever its step (one included), reads only literals, addresses, and locals or parameters that neither
the loop nor a pointer can write, and the start runs again before each entry of the loop, so it is the same value on every
pass. A global, a dereference or a call is refused. The exact judge decides.
"""
import re

from . import counted_loop_shapes, stepped_induction_index
from .integer_repair_support import IDENT, edit, view
from .loop_invariance import CAST, WORD, declared, runs_each_time, stable
from .pattern_repairs import close

FAMILY = 'integer_cursor_for_loop'
BOUND_LOCAL = 'integer_cursor_for_loop_bound_local'
FAMILIES = (FAMILY, BOUND_LOCAL)
_FOR = re.compile(rf'\bfor\s*\(\s*(?P<i>{IDENT}) = 0; (?P=i) < (?P<n>{IDENT});')


def _starts_stable(part):
    """Whether every start `stepped_induction_index`'s first child would repeat is the same value on every pass."""
    clean = part.clean
    for loop in stepped_induction_index._loops(part):
        opening, end, tail, run, strides = loop
        before = clean[part.opening + 1:opening]
        # `before` ends with the loop's `do`; its brace is `opening`
        assigns = list(stepped_induction_index._ASSIGN.finditer(before))
        for counter in [v for v, k in strides.items() if k == 1]:
            zero = [a for a in assigns if a['v'] == counter]
            if not zero or zero[-1]['init'].strip() not in ('0', '0U'):
                continue
            # the same choice, in the same order, as the child `variants` takes
            chosen = [v for v in strides if v != counter
                      and stepped_induction_index._plan(part, loop, counter, v, strides[v])]
            if not chosen:
                continue
            if not stepped_induction_index._counter_proven(part, loop, counter):
                return False
            if not all(stepped_induction_index._start_proven(part, loop, var) for var in chosen):
                return False
            return True
    return False


def _inline_bound(source, name):
    """`n = EXPR; ... for (i = 0; i < n; ..)` with EXPR written in the test, when the test is the only reader of n."""
    part = view(source, name)
    if not part:
        return None
    clean = part.clean
    for loop in _FOR.finditer(clean, part.opening, part.end):
        n = loop['n']
        kind = declared(part, n)
        body = clean[part.opening + 1:part.end - 1]
        offset = part.opening + 1
        copies = list(re.finditer(rf'(?m)^[ \t]*{n} = {n};[ \t]*\n', body))
        sets = [s for s in re.finditer(rf'(?m)^[ \t]*{n} = (?P<value>[^;{{}}=]+);[ \t]*\n', body)
                if s['value'].strip() != n]
        if not kind or len(sets) != 1 or offset + sets[0].end() > loop.start():
            continue
        if not runs_each_time(body[:loop.start() - offset], sets[0]):
            continue
        declaration = re.search(rf'(?m)^[ \t]*{re.escape(kind)}\s*\b{n}\s*;', body)
        known = [(s.start(), s.end()) for s in copies + sets] + ([declaration.span()] if declaration else [])
        known.append((loop.start('n') - offset, loop.end('n') - offset))
        if any(not any(a <= use.start() < b for a, b in known) for use in re.finditer(rf'\b{n}\b', body)):
            continue
        value = sets[0]['value'].strip()
        opening = clean.find('(', loop.start())
        header_end = close(clean, opening, '(', ')')
        brace = clean.find('{', header_end) if header_end else -1
        loop_end = close(clean, brace, '{', '}') if brace >= 0 else None
        if not loop_end or not stable(part, value, clean[offset + sets[0].end():loop_end]):
            continue
        words = [w['v'] for w in WORD.finditer(CAST.sub(' ', value))]
        text = f'({value})' if all(declared(part, w) == kind for w in words) else f'({kind})({value})'
        edits = [(offset + s.start(), offset + s.end(), '') for s in copies + sets]
        edits.append((loop.start('n'), loop.end('n'), text))
        return edit(source, edits)
    return None


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\bvolatile\b', part.clean[part.opening:part.end]) or not _starts_stable(part):
        return []
    indexed = stepped_induction_index.variants(source, name)
    if not indexed:
        return []
    text = indexed[0][1]
    for family, child in counted_loop_shapes.variants(text, name):
        if family != 'counted_for_loop':
            continue
        child = re.sub(r'(?m)\n[ \t]*\n(?=for \()', '\n', child)
        inlined = _inline_bound(child, name)
        return ([(FAMILY, inlined)] if inlined else []) + [(BOUND_LOCAL, child)]
    return []


REPAIR = {
    'families': FAMILIES,
    'variants': variants,
    'needs': ('source', 'name'),
    'order': 400,
}
