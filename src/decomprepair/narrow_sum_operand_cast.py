"""A parenthesised sum cast to the narrow store's own type, so the constant is added to the variable first.

    *(u16 *)(q + 0x20) = W + (x + 0xFFC7U);        ->        *(u16 *)(q + 0x20) = W + (u16) (x + 0xFFC7U);

The stored value is only the low 16 (or 8) bits, so the cast changes no value, but it changes the tree the compiler
builds. fold-const reassociates `W + (x + K)` into one chain that adds the constant to the first loaded operand
(`(W + K) + x`: the global's load, `ori`, `addu`, then the variable's reload), whichever way the source orders the
operands (`x + K + W` and `(x + K) + W` compile identically). A narrowing cast around the inner sum keeps it a unit:
`(x + K)` is added first and the other operand last, the order a target shows when its first `addu` has the variable.
On a KMC GCC 2.7.2 menu builder (`-G0 -mips3 -mgp32 -mfp32 -O2`, 535 instructions) the one edit took 420 -> 330 and
closed the two rows of a load-order difference; a neighbouring statement with the same shape and no cast was already
exact, so the child is offered per statement (the candidate is never a verdict: the judge decides).
Hypothesis (not confirmed in fold-const.c): the cast stops `associate` from splitting the literal out of the inner sum.

Child, for an assignment whose left side is a narrow store (`*(T *)(...)` or an array declared in the source with a
8- or 16-bit element type) and whose right side has a parenthesised sum `(a + K)` / `(a - K)` as an operand of a top-level
`+` or `-`, with a literal in it, and no cast already: the sum wrapped in `(T)`. One child per statement and one with
every statement (`narrow_sum_operand_cast_all`).
"""
import re

from . import csource
from .csource import _blank

FAMILY = 'narrow_sum_operand_cast'
FAMILY_ALL = 'narrow_sum_operand_cast_all'
FAMILIES = (FAMILY, FAMILY_ALL)
_NARROW = r'(?:u8|s8|u16|s16|char|short|unsigned char|unsigned short|signed char|signed short)'
_DEREF = re.compile(rf'^\(?\s*\*\s*\(\s*(?P<t>{_NARROW})\s*\*\s*\)')
_INDEX = re.compile(r'^\(?\s*(?P<name>[A-Za-z_]\w*)\s*\[')
_STATEMENT = re.compile(r'(?<![=!<>+\-*/&|^%])(?P<lhs>[^;{}=\n][^;{}=]*?)\s=\s(?P<rhs>[^;{}=][^;{}]*?);')
_LITERAL = re.compile(r'(?<![\w.])(?:0[xX][0-9A-Fa-f]+|\d+)[uUlL]*(?![\w.])')


def _element_types(clean):
    """{array name: narrow element type} for the arrays the source declares."""
    out = {}
    for m in re.finditer(rf'(?:^|[;{{}}\n])\s*(?:extern\s+)?(?P<t>{_NARROW})\s+(?P<n>[A-Za-z_]\w*)\s*\[', clean):
        out[m['n']] = m['t']
    return out


def _store_type(lhs, arrays):
    d = _DEREF.match(lhs.strip())
    if d:
        return d['t']
    i = _INDEX.match(lhs.strip())
    if i:
        return arrays.get(i['name'])
    return None


def _groups(rhs):
    """[(start, end)] of the parenthesised operands of a top-level `+`/`-` that are themselves sums with a literal."""
    out, depth, i = [], 0, 0
    top_ops = 0
    for c in rhs:
        if c in '([':
            depth += 1
        elif c in ')]':
            depth -= 1
        elif c in '+-' and depth == 0:
            top_ops += 1
    if not top_ops:
        return out
    while i < len(rhs):
        c = rhs[i]
        if c == '(':
            before = rhs[:i].rstrip()
            level, j = 0, i
            while j < len(rhs):
                level += (rhs[j] == '(') - (rhs[j] == ')')
                if level == 0:
                    break
                j += 1
            inner = rhs[i + 1:j]
            at_top = rhs[:i].count('(') - rhs[:i].count(')') == 0
            after_op = before.endswith(('+', '-'))
            cast_like = before.endswith(')') or re.search(r'\w$', before)
            sum_inside, d = False, 0
            for k, ch in enumerate(inner):
                if ch in '([':
                    d += 1
                elif ch in ')]':
                    d -= 1
                elif ch in '+-' and d == 0 and k > 0 and inner[:k].strip() and not re.search(r'[+\-*/(<>=&|^%]\s*$', inner[:k]):
                    sum_inside = True
            if at_top and after_op and not cast_like and sum_inside and _LITERAL.search(inner) and not re.match(r'\s*\(?\s*' + _NARROW, inner):
                out.append((i, j + 1))
            i = j + 1
            continue
        i += 1
    return out


def _edits(source, name):
    span = csource.find(source, name)
    if not span:
        return []
    clean = _blank(source)
    arrays = _element_types(clean)
    out = []
    for m in _STATEMENT.finditer(clean, *span):
        t = _store_type(m['lhs'], arrays)
        if not t:
            continue
        rhs = source[m.start('rhs'):m.end('rhs')]
        for lo, hi in _groups(clean[m.start('rhs'):m.end('rhs')]):
            out.append((m.start('rhs') + lo, m.start('rhs') + hi, t, rhs[lo:hi]))
    return out


def _apply(source, edits):
    for lo, hi, t, text in sorted(edits, reverse=True):
        source = source[:lo] + f'({t}) {text}' + source[hi:]
    return source


def variants(source, name):
    edits = _edits(source, name)
    out = [(FAMILY, _apply(source, [e])) for e in edits]
    if len(edits) > 1:
        out.append((FAMILY_ALL, _apply(source, edits)))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
