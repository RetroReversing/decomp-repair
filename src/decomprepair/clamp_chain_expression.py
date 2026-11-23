"""A three-way clamp assigned to a local in every arm and then stored: the conditional expression it came from.

Matched on a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) scroll-window update that stood at 3265: a selected row
index was stepped by one and kept inside `0 .. count - 1`. m2c wrote the step into a wide `proposed` local, a byte local
`selected` that every arm of the clamp assigned, and a store of `selected`. The target has no local for the clamped value:
the store takes the value in the register of the last arm, and the third arm recomputes `selected + 1` from the loaded
byte (`addiu $v0,$a1,1` after the `slt`). Writing the three arms as one conditional expression that is stored directly
(`w->selected = w->selected + 1 < 0 ? 0 : w->selected + 1 > w->count - 1 ? w->count - 1 : w->selected + 1;`) gave that
shape and dropped the score from 3265 to 2415 in one step.

clamp_chain_expression
    `t = E; if (t < lo) v = lo; else if (t > hi) v = hi; else v = t; dst = v;` becomes `dst = E < lo ? lo : E > hi ? hi :
    E;`. The expression is repeated, so the family offers it only for an expression with no call and no side effect,
    and only when neither `t` nor `v` is read afterwards (a write is fine). Hypothesis from the match, not from the
    compiler source: with no local for the result the store narrows each arm itself and cse keeps the first compare's
    value only for the compares.

The exact judge decides every child; nothing here proves it is the compiler's reason.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'clamp_chain_expression'
FAMILIES = (FAMILY,)
LIMIT = 4
_HEAD = re.compile(rf'(?P<t>{IDENT})\s*=\s*(?P<expr>[^;{{}}=][^;{{}}]*?)\s*;\s*')
_OPERAND = r'[\w.>\s+*-]+'


def _names(text, name):
    """The occurrences of the local `name`, not the members that happen to be called that."""
    return [m for m in re.finditer(rf'\b{re.escape(name)}\b', text) if not re.search(r'(?:->|\.)\s*$', text[:m.start()])]


def _arm(clean, at, variable=None):
    """`v = x;` (optionally braced) at `at`: (variable, value, end) or None."""
    found = re.compile(rf'\s*(?:\{{\s*)?(?P<v>{IDENT})\s*=(?!=)\s*(?P<x>[^;{{}}]+?)\s*;\s*(?:\}}\s*)?').match(clean, at)
    if not found or (variable and found['v'] != variable):
        return None
    return found['v'], found['x'].strip(), found.end()


def _compare(clean, at, t):
    """`if (t OP bound)` at `at`: (OP, bound, end) or None."""
    head = re.compile(r'\s*if\s*\(').match(clean, at)
    if not head:
        return None
    stop = close(clean, head.end() - 1)
    if stop is None:
        return None
    inside = clean[head.end():stop - 1]
    found = re.fullmatch(rf'\s*{re.escape(t)}\s*(<=|>=|<|>)\s*({_OPERAND})\s*', inside)
    return (found[1], found[2].strip(), stop) if found else None


def _operand(text):
    text = text.strip()
    return text if re.fullmatch(r'[\w.>\s+*-]+', text) else f'({text})'


def _children(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|goto|asm|__asm__)\b', part.body):
        return []
    clean, result = part.clean, []
    for head in _HEAD.finditer(clean, part.opening + 1, part.end):
        t, expr = head['t'], head['expr'].strip()
        if _names(expr, t) or re.search(IDENT + r'\s*\(|\+\+|--|[^=!<>]=[^=]', expr):
            continue
        first = _compare(clean, head.end(), t)
        if not first or first[0] not in ('<', '<='):
            continue
        low = _arm(clean, first[2])
        if not low:
            continue
        v = low[0]
        elsepart = re.compile(r'\s*else\b').match(clean, low[2])
        if not elsepart:
            continue
        second = _compare(clean, elsepart.end(), t)
        if not second or second[0] not in ('>', '>='):
            continue
        high = _arm(clean, second[2], v)
        last = re.compile(r'\s*else\b').match(clean, high[2]) if high else None
        final = _arm(clean, last.end(), v) if last else None
        if not final or final[1] != t:
            continue
        store = re.compile(rf'\s*(?P<dst>[^;={{}}\n]+?)\s*=\s*{re.escape(v)}\s*;').match(clean, final[2])
        if not store or '==' in store['dst'] or re.search(r'[<>!]', store['dst'].replace('->', '')):
            continue
        if any(re.search(IDENT + r'\s*\(|\+\+|--', x) for x in (first[1], second[1], low[1], high[1])):
            continue
        later = clean[store.end():part.end]
        if any(not re.match(r'\s*=(?!=)', later[m.end():]) for name_ in (t, v) for m in _names(later, name_)):
            continue
        operand = _operand(expr)
        lo, hi = _operand(low[1]), _operand(high[1])
        body = (f'{store["dst"].strip()} = {operand} {first[0]} {_operand(first[1])} ? {lo} : '
                f'{operand} {second[0]} {_operand(second[1])} ? {hi} : {operand};')
        result.append((FAMILY, edit(source, [(head.start(), store.end(), body)])))
    return result[:LIMIT]


def variants(source, name):
    return _children(source, name)


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
