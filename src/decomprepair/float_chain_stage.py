"""A float assigned from a chain of binary operations, written one operation per statement.

`v = ((a / b) * 30.0f) - 15.0f;` against `v = a / b; v = v * 30.0f; v = v - 15.0f;`. On KMC GCC 2.7.2 (N64) the
one-expression form keeps each intermediate in a temporary that takes the lowest free float register, so the divide's
result and the constants swap registers (`div.s $f0` with the constant in `$f2`); written one operation at a time every
intermediate is the variable's own pseudo, which is allocated before the constants, and the target's `div.s $f2` then
the constants in `$f0` appear. A text-layout function's scale computation sat at 415 with eight float register rows;
this one edit took the function to 390 and was one of five steps that together reached 95. `compound_operand_split` splits
a statement with exactly one operator and leaves a nested left operand whole, so the chain stayed out of its reach (its
child on the same statement scored 405). Hypothesis (not confirmed in the compiler's source): local-alloc's quantity
ordering of the temporaries against the variable decides it; the measured fact is the register swap.

Children, for a float local assigned from a left-leaning chain of two or more binary `*`, `/`, `+` or `-` operations
whose other operands do not mention it and call nothing: the chain as `v = first; v = v op next; ...` and as
`v = first; v op= next; ...`, each statement on its own, and every such statement of the function together as one
child. A statement under an unbraced `if` is left alone. Only MIPS, and a function with no `volatile`. The candidate is
never a verdict: the judge decides.
"""
import re

from .compound_operand_split import _STATEMENT, _float_names, _paren, _simple, _split
from .csource import _blank, find

FAMILY = 'float_chain_stage'
FAMILIES = (FAMILY,)
_LIMIT = 16


def _python_unwrap(text):
    """`text` without redundant outer parentheses (`(a / b)` -> `a / b`), only when they enclose all of it."""
    text = text.strip()
    while text.startswith('(') and text.endswith(')'):
        depth = 0
        for i, c in enumerate(text):
            depth += (c == '(') - (c == ')')
            if depth == 0 and i < len(text) - 1:
                return text
        text = text[1:-1].strip()
    return text


_unwrap = _python_unwrap
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _unwrap(text):
        found = _scan.unwrap_parens(text)
        return _python_unwrap(text) if found is NotImplemented else found


def _chain(expr, name):
    """[(first_left, first_op, first_right), (op, right), ...] of a left-leaning chain of 2+ operations, else None."""
    steps = []
    current = _unwrap(expr)
    while True:
        parts = _split(current)
        if not parts:
            break
        left, op, right = parts
        if not _simple(right, name):
            return None
        steps.append((op, right))
        current = _unwrap(left)
    if len(steps) < 2 or not (current == name or _simple(current, name)):
        return None
    steps.reverse()
    first_op, first_right = steps[0]
    return (current, first_op, first_right), steps[1:]


def _operand(text):
    return _paren(_unwrap(text))


def _staged(name, chain, indent, compound):
    (left, op, right), rest = chain
    lines = [f'{name} = {_operand(left)} {op} {_operand(right)};']
    for op, right in rest:
        lines.append(f'{name} {op}= {_operand(right)};' if compound else f'{name} = {name} {op} {_operand(right)};')
    return f'\n{indent}'.join(lines)


def _children(clean, lo, hi, floats):
    out = []
    for hit in _STATEMENT.finditer(clean, lo, hi):
        name = hit[2]
        if name not in floats:
            continue
        chain = _chain(hit[3], name)
        if chain:
            out.append((hit.start(2), hit.end(), name, chain, hit[1].split('\n')[-1]))
    return out[:_LIMIT]


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    if opening < 0 or re.search(r'\bvolatile\b', clean[span[0]:span[1]]):
        return []
    found = _children(clean, opening, span[1], _float_names(clean[span[0]:span[1]]))
    out = []
    for compound in (False, True):
        for start, end, var, chain, indent in found:
            out.append((FAMILY, source[:start] + _staged(var, chain, indent, compound) + source[end:]))
        if len(found) > 1:
            src = source
            for start, end, var, chain, indent in reversed(found):
                src = src[:start] + _staged(var, chain, indent, compound) + src[end:]
            out.append((FAMILY, src))
    return [x for x in out if x[1] != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
