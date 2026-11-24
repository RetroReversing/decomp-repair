"""An array element's compound update (`H[x] += 1;`) staged through a temporary, its store after the next counter step.

GCC 2.7.2's local-alloc.c sorts a block's local quantities itself when there are exactly three (the
`case 3:` exchanges in `block_alloc`), and `qty_compare` there takes quantity numbers (birth order), not
positions, so the order it allocates in is not the priority order (docs/learnings/finding/local-alloc-three-quantity-block-sort.md
in decompdecomp). A histogram loop's body `*q = len; H[len] += 1; i++; q++;` (KMC GCC 2.7.2, a 681-instruction N64
bit-stream decoder) has three: the element address, the loaded count and the loop test. The address was born
first and came out first (`$v0`), the count second (`$v1`); the target had them the other way round, with every
spelling of the update giving the same code. Written `{ u32 hv = H[len] + 1; i++; H[len] = hv; }`, the count and
the address live two insns longer, the loop test now outranks the count, and the buggy exchange hands out
count, test, address: the target's registers (110 -> 85 on the decoder, every output, error word and table equal
on 1500 generated streams).

A child for each compound update `A[i] op= e;` (op one of + - & | ^, A an integer array or pointer whose element type
the function or the file declares) followed by a counter step (`n++;`, `n--;`, `++n;`, `n += K;`, `n -= K;`) on a
name the update does not mention: the step moved between the load and the store, once with the operation before the
step and once after it; with two steps in a row, also both moved. A candidate rewrite; the exact judge decides.
"""
import re

from .integer_repair_support import INTEGER, edit, view

FAMILY = 'rmw_store_past_step'
FAMILIES = (FAMILY,)
LIMIT = 24
_UPDATE = re.compile(r'(?m)^([ \t]*)([A-Za-z_]\w*)\[([^\[\];]+)\]\s*([-+&|^])=\s*([^;]+);[ \t]*\n')
_STEP = re.compile(r'[ \t]*(?:([A-Za-z_]\w*)\s*(?:\+\+|--)|(?:\+\+|--)\s*([A-Za-z_]\w*)|([A-Za-z_]\w*)\s*[-+]=\s*'
                   r'(?:0[xX][0-9a-fA-F]+|\d+)[uU]?)\s*;[ \t]*\n')


def _element_type(text, base):
    """The integer element type `base` is declared with (`u32 *H;`, `u32 H[4];`, `extern u32 H[];`), or None."""
    hits = re.findall(rf'\b({INTEGER})\s*(\*\s*)?{re.escape(base)}\s*(\[)?', text)
    types = {re.sub(r'\s+', ' ', t) for t, star, bracket in hits if star or bracket}
    return types.pop() if len(types) == 1 else None


def _fresh(text, stem):
    name, n = stem, 1
    while re.search(rf'\b{name}\b', text):
        n += 1
        name = f'{stem}{n}'
    return name


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean, lo, hi = part.clean, part.opening + 1, part.end - 1
    if re.search(r'\bvolatile\b', clean[lo:hi]):
        return []
    out = []
    for update in _UPDATE.finditer(clean, lo, hi):
        indent, base, index, op, value = update.groups()
        ttype = _element_type(clean[:hi] + '\n' + header, base)
        if not ttype:
            continue
        mentioned = set(re.findall(r'[A-Za-z_]\w*', update[0]))
        steps, at = [], update.end()
        while len(steps) < 2:
            step = _STEP.match(clean, at)
            if not step or (step[1] or step[2] or step[3]) in mentioned:
                break
            steps.append(step)
            at = step.end()
        temp = _fresh(clean, 'hv')
        src = lambda g, u=update: source[u.start(g):u.end(g)].strip()  # noqa: E731
        lval = f'{base}[{src(3)}]'
        operand = src(5) if re.fullmatch(r'\w+', src(5)) else f'({src(5)})'
        for count in range(1, len(steps) + 1):
            moved = ' '.join(source[s.start():s.end()].strip() for s in steps[:count])
            end = steps[count - 1].end()
            before = f'{indent}{{ {ttype} {temp} = {lval} {op} {operand}; {moved} {lval} = {temp}; }}\n'
            after = f'{indent}{{ {ttype} {temp} = {lval}; {moved} {lval} = {temp} {op} {operand}; }}\n'
            out.extend((FAMILY, edit(source, [(update.start(), end, text)])) for text in (before, after))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}  # the registry: no caller wiring (registry.py)
