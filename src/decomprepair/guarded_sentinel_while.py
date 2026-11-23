"""A sentinel guard over a do-while with the same test, written as the plain `while` it stands for.

Matched on a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) voice-picker that walked two chains of byte links: for
every chain position it read the first link and then followed `next` until the 0xFF sentinel. m2c wrote the walk as

    idx = first[pos];
    if (idx != 0xFF) {
        do { ...; idx = next[idx]; } while (idx != 0xFF);
    }

and the target has two separate registers holding 255, one hoisted out of the whole search loop for the guard and one
loaded in the inner loop's own preheader for the bottom test (`addiu $s1,$zero,0xff` before the search loop and
`addiu $t7,$zero,0xff` after the guard's branch). The guard and the loop test are one expression in the guarded
`do { } while`, so cse folds both constants into one register; written as `while (idx != 0xFF) { ... }` the compiler
duplicates the loop's entry test itself (jump.c) and the bottom test is a block of its own that cse cannot join to the
guard. With all three such walks of that function rewritten together the score went 2310 -> 1550 (a single walk
alone is not the measured step: the registers move once every walk has its own constant).

guarded_sentinel_while
    `if (C) { do { B } while (C); }` (or `if (C) do { B } while (C);`) becomes `while (C) { B }` when the two
    conditions are the same text with no call, assignment, `++` or `--` in it, nothing follows the `if` as an `else`,
    and the body holds no `goto`, label or `case`. One child per such pair, and one child with all of them when there
    are two or more. Hypothesis from the match, not from the compiler source: the entry test of a `while` is copied by
    the loop-test duplication in jump.c, after the cse that would otherwise join its constant with the guard's.

The exact judge decides every child; nothing here proves it is the compiler's reason.
"""
import re

from .c_scan import close, normal
from .integer_repair_support import edit, view

FAMILY = 'guarded_sentinel_while'
FAMILIES = (FAMILY,)
LIMIT = 8
_IF = re.compile(r'\bif\s*\(')
_DO = re.compile(r'\s*do\b\s*')
_WHILE = re.compile(r'\s*while\s*\(')
_IMPURE = re.compile(r'\+\+|--|(?<![=!<>])=(?!=)|[A-Za-z_]\w*\s*\(|\bvolatile\b')
_BLOCKED = re.compile(r'\bgoto\b|\bcase\b|\bdefault\b|^\s*[A-Za-z_]\w*\s*:(?!:)', re.M)


def _pairs(clean, source, low, high):
    """(start, end, replacement) for each `if (C) [{] do { B } while (C); [}]` in clean[low:high]."""
    found = []
    for hit in _IF.finditer(clean, low, high):
        opening = hit.end() - 1
        closing = close(clean, opening, '(', ')')
        if closing < 0:
            continue
        condition = clean[opening + 1:closing]
        if _IMPURE.search(condition) or not condition.strip():
            continue
        position = closing + 1
        braced = clean[position:].lstrip()[:1] == '{'
        if braced:
            position = clean.index('{', position) + 1
        do = _DO.match(clean, position)
        if not do:
            continue
        body_open = do.end()
        if clean[body_open:body_open + 1] != '{':
            continue
        body_close = close(clean, body_open)
        if body_close < 0:
            continue
        tail = _WHILE.match(clean, body_close + 1)
        if not tail:
            continue
        test_open = tail.end() - 1
        test_close = close(clean, test_open, '(', ')')
        after = re.match(r'\s*;', clean[test_close + 1:]) if test_close > 0 else None
        if not after or normal(clean[test_open + 1:test_close]) != normal(condition):
            continue
        end = test_close + 1 + after.end()
        if braced:
            rest = re.match(r'\s*\}', clean[end:])
            if not rest:
                continue
            end += rest.end()
        if re.match(r'\s*else\b', clean[end:]) or _BLOCKED.search(clean[body_open:body_close]):
            continue
        found.append((hit.start(), end,
                      f'while ({source[opening + 1:closing].strip()}) {source[body_open:body_close + 1]}'))
    return found


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    pairs = _pairs(part.clean, source, part.opening + 1, part.end)
    # a pair nested inside another one is edited by the outer edit alone
    pairs = [p for p in pairs if not any(q is not p and q[0] < p[0] and p[1] <= q[1] for q in pairs)][:LIMIT]
    children = [(FAMILY, edit(source, [p])) for p in pairs]
    if len(pairs) > 1:
        children.append((FAMILY, edit(source, pairs)))
    return children


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
