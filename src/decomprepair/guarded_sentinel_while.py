"""A sentinel guard over a do-while with the same test, written as the plain `while` it stands for.

guard_prefix_while (a stream refill, `ido-7.1`, 60 -> 0 as the last step of a 222-instruction match): m2c's guard
`if (P && Q) { do { B } while (Q); }` repeats only the trailing operands Q at the bottom; the target's loop is a `while`
whose entry test is Q, nested in an `if (P)`. Written as `if (P) { while (Q) { B } }` the compiler lays the entry
test out as the target does; the nested form is the same program when Q has no side effect (it is read once in the
guard and once at the loop's entry, with nothing in between that P could change).

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

guard_first_test_while
    The loop's first test written into the guard with the counter's start value substituted, as m2c writes a `while`
    whose first iteration it could fold: `if (G && t[8] == 0) { i = 0; do { B } while (t[8 + i] == 0 && i < 4); R }`
    becomes `if (G) { i = 0; while (t[8 + i] == 0 && i < 4) { B } R }`. The other loop operands must hold at the start
    value (`i < K`, K above it) and every statement R after the loop must repeat the one just before the `if`, since R
    then also runs when the first test fails. Measured on a KMC gcc 2.7.2 (`-O1`) digit-filling loop: 2000 -> 1575
    alone, 1020 -> 730 after four other repairs.

The exact judge decides every child; nothing here proves it is the compiler's reason.
"""
import re

from .c_scan import close, normal
from .integer_repair_support import edit, view

FAMILY = 'guarded_sentinel_while'
PREFIX = 'guard_prefix_while'
FIRST = 'guard_first_test_while'
FAMILIES = (FAMILY, PREFIX, FIRST)
LIMIT = 8
_IF = re.compile(r'\bif\s*\(')
_DO = re.compile(r'\s*do\b\s*')
_WHILE = re.compile(r'\s*while\s*\(')
_IMPURE = re.compile(r'\+\+|--|(?<![=!<>])=(?!=)|[A-Za-z_]\w*\s*\(|\bvolatile\b')
_BLOCKED = re.compile(r'\bgoto\b|\bcase\b|\bdefault\b|^\s*[A-Za-z_]\w*\s*:(?!:)', re.M)


def _python_conjuncts(clean, low, high):
    """The (start, end) offsets of the top-level `&&` operands of clean[low:high]."""
    spans, depth, start, i = [], 0, low, low
    while i < high:
        c = clean[i]
        if c in '([':
            depth += 1
        elif c in ')]':
            depth -= 1
        elif depth == 0 and clean.startswith('&&', i):
            spans.append((start, i))
            start, i = i + 2, i + 1
        i += 1
    spans.append((start, high))
    return spans


_conjuncts = _python_conjuncts
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _conjuncts(clean, low, high):
        found = _scan.conjuncts(clean, low, high)
        return _python_conjuncts(clean, low, high) if found is NotImplemented else found


def _prefix(clean, low, high, test):
    """The offset where the guard's trailing operands, equal to the loop's test, begin, and the end of the operands
    before them; None when no proper suffix of the guard is the test (or the guard has one operand)."""
    spans = _conjuncts(clean, low, high)
    for k in range(1, len(spans)):
        if normal(clean[spans[k][0]:high]) == normal(test):
            return spans[k - 1][1]
    return None


def _pairs(clean, source, low, high):
    """(start, end, replacement, family) for each `if (C) [{] do { B } while (C); [}]` in clean[low:high], and for each
    `if (P && C) do { B } while (C);`, whose leading operands P are no part of the loop's test."""
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
        if not after:
            continue
        test = clean[test_open + 1:test_close]
        family, head = FAMILY, None
        if normal(test) != normal(condition):
            head = _prefix(clean, opening + 1, closing, test)
            if head is None:
                continue
            family = PREFIX
        end = test_close + 1 + after.end()
        if braced:
            rest = re.match(r'\s*\}', clean[end:])
            if not rest:
                continue
            end += rest.end()
        if re.match(r'\s*else\b', clean[end:]) or _BLOCKED.search(clean[body_open:body_close]):
            continue
        loop = f'while ({source[test_open + 1:test_close].strip()}) {source[body_open:body_close + 1]}'
        if head is not None:
            loop = f'if ({source[opening + 1:head].strip()}) {{ {loop} }}'
        found.append((hit.start(), end, loop, family))
    return found


_START = re.compile(r'\s*\{\s*([A-Za-z_]\w*)\s*=\s*(0)\s*;\s*do\b\s*')


def _at_start(text, counter, value):
    """`text` with the counter at its start value, whitespace and `+ 0` dropped."""
    text = re.sub(rf'\b{re.escape(counter)}\b', value, text)
    return re.sub(r'\+0(?![\w.])|(?<![\w.])0\+', '', re.sub(r'\s+', '', text))


def _first_tests(clean, source, low, high):
    """(start, end, replacement) for each guard that spells the do-while's first test with the counter folded."""
    found = []
    for hit in _IF.finditer(clean, low, high):
        opening = hit.end() - 1
        closing = close(clean, opening, '(', ')')
        if closing < 0 or _IMPURE.search(clean[opening + 1:closing]):
            continue
        brace = closing + 1 + len(clean[closing + 1:]) - len(clean[closing + 1:].lstrip())
        if clean[brace:brace + 1] != '{':
            continue
        block_end = close(clean, brace)
        start = _START.match(clean, brace)
        if block_end < 0 or not start or clean[start.end():start.end() + 1] != '{':
            continue
        body_close = close(clean, start.end())
        tail = _WHILE.match(clean, body_close + 1) if body_close > 0 else None
        if not tail:
            continue
        test_open = tail.end() - 1
        test_close = close(clean, test_open, '(', ')')
        after = re.match(r'\s*;', clean[test_close + 1:]) if test_close > 0 else None
        if not after:
            continue
        test = clean[test_open + 1:test_close]
        if _IMPURE.search(test) or _BLOCKED.search(clean[start.end():body_close]):
            continue
        counter, value = start[1], start[2]
        guards = _conjuncts(clean, opening + 1, closing)
        loop = _conjuncts(clean, test_open + 1, test_close)
        if len(guards) < 2:
            continue
        first = _at_start(clean[loop[0][0]:loop[0][1]], counter, value)
        others = [clean[a:b].strip() for a, b in loop[1:]]
        bounds = [re.fullmatch(rf'{re.escape(counter)}\s*<\s*(\d+)', other) for other in others]
        if (_at_start(clean[guards[-1][0]:guards[-1][1]], counter, value) != first
                or not all(b and int(b[1]) > int(value) for b in bounds)):
            continue
        rest_start = test_close + 1 + after.end()
        before = normal(clean[:hit.start()])
        repeats = [part for part in clean[rest_start:block_end].split(';') if part.strip()]
        if any(not re.fullmatch(r'\s*[A-Za-z_]\w*\s*=\s*[A-Za-z_]\w*\s*', part)
               or not before.endswith(normal(part) + ';') for part in repeats):
            continue
        if re.match(r'\s*else\b', clean[block_end + 1:]):
            continue
        guard = source[opening + 1:guards[-2][1]].strip()
        replacement = (f'if ({guard}) {{ {counter} = {value}; while ({source[test_open + 1:test_close].strip()}) '
                       f'{source[start.end():body_close + 1]}{source[rest_start:block_end]}}}')
        found.append((hit.start(), block_end + 1, replacement))
    return found[:LIMIT]


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    pairs = _pairs(part.clean, source, part.opening + 1, part.end)
    # a pair nested inside another one is edited by the outer edit alone
    pairs = [p for p in pairs if not any(q is not p and q[0] < p[0] and p[1] <= q[1] for q in pairs)][:LIMIT]
    children = [(p[3], edit(source, [p[:3]])) for p in pairs]
    for family in (FAMILY, PREFIX):
        same = [p[:3] for p in pairs if p[3] == family]
        if len(same) > 1:
            children.append((family, edit(source, same)))
    for found in _first_tests(part.clean, source, part.opening + 1, part.end):
        children.append((FIRST, edit(source, [found])))
    return children


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
