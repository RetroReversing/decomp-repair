"""A loop's entry guard written as the loop's own first test: `v = 0; if (n != 0)` becomes `v = 0; if (v < n)`.

A `for (i = 0; i < n; i++)` loop is inverted by GCC 2.7.2: the compiler tests `i < n` once before the body and then at
the bottom. m2c, seeing the guard fold to `n != 0` in the assembly, writes `if (n != 0)`. The two read the same, but
the compiler keeps a difference: the original's guard compare is an `ltu` insn whose result pseudo is later folded
away, and every such dead pseudo still gets a spill slot in the frame (reload.c allocates one for each pseudo that
has references and no hard register). A guard written `n != 0` leaves no such pseudo, so the frame comes out smaller
and every spill slot after the first lands at another offset (a 4-loop function was 24 bytes short: 31 differing
stack rows, 0 once three or four of the guards were written as the loop's own test).

A proposal rewrites one guard `if (X != 0)` (or `if (X)`) as `if (v < X)` when the statement right before it is
`v = 0;` and the guarded body holds a loop that tests `v` against the same text, with `v` not otherwise used between
the init and the guard. Each guard is offered alone and all together, because the frame needs a number of them that
only the measurement knows. MIPS only.
"""
import re

from .csource import _blank, find

FAMILY = 'guard_counter_compare'
FAMILIES = (FAMILY,)
LIMIT = 24

_ID = r'[A-Za-z_]\w*'
_EFFECT = re.compile(r'\+\+|--|(?<![=!<>])=(?!=)|\w\s*\(')
_INIT_BEFORE = re.compile(rf'({_ID})\s*=\s*0\s*;\s*$')


def _close(clean, start, left, right):
    depth = 0
    for pos in range(start, len(clean)):
        depth += (clean[pos] == left) - (clean[pos] == right)
        if depth == 0:
            return pos + 1
    return None


def _squash(text):
    return re.sub(r'\s+', '', text)


def _guards(source, clean, opening, closing):
    """(start of the condition text, end, its operand X, the counter) for each `v = 0; if (X != 0) { ... while (v < X) }`."""
    found = []
    for guard in re.finditer(r'\bif\s*\(', clean[opening:closing]):
        at = opening + guard.start()
        paren = opening + guard.end() - 1
        paren_end = _close(clean, paren, '(', ')')
        if not paren_end:
            continue
        condition = clean[paren + 1:paren_end - 1]
        compare = re.fullmatch(r'\s*(.+?)\s*!=\s*0\s*', condition, re.S)
        operand = compare[1] if compare else condition.strip()
        if not operand or _EFFECT.search(operand) or re.search(r'[<>=!&|]', operand.replace('->', '')):
            continue
        previous = _INIT_BEFORE.search(clean[opening + 1:at].rstrip())
        if not previous:
            continue
        counter = previous[1]
        brace = re.compile(r'\s*\{').match(clean, paren_end)
        body_end = _close(clean, brace.end() - 1, '{', '}') if brace else None
        if not body_end:
            continue
        body = _squash(clean[brace.end():body_end])
        flat = _squash(operand)
        # a loop whose test mentions the counter, a `<`, and the guard's operand (possibly under a cast)
        tests = re.findall(r'while\((.*?)\);', body)
        if not any(counter in test and '<' in test and flat in test for test in tests):
            continue
        found.append((paren + 1, paren_end - 1, source[paren + 1:paren_end - 1], counter, operand.strip()))
    return found


def variants(source, name, arch='mips'):
    """Proposals: entry guards rewritten as the counter's first test, one at a time and all at once."""
    if arch != 'mips':
        return []
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    closing = clean.rfind('}', 0, span[1])
    if opening < 0 or closing < opening or re.search(r'^\s*#', clean[span[0]:span[1]], re.M):
        return []
    found = _guards(source, clean, opening, closing)
    if not found:
        return []

    def rewrite(chosen):
        new = source
        for start, end, _, counter, operand in sorted(chosen, reverse=True):
            new = new[:start] + f'{operand} > {counter}' + new[end:]
        return new

    out = [(FAMILY, rewrite([one])) for one in found]
    if len(found) > 1:
        out.append((FAMILY, rewrite(found)))
        for skip in range(len(found)):
            out.append((FAMILY, rewrite(found[:skip] + found[skip + 1:])))
    seen, unique = set(), []
    for item in out:
        if item[1] not in seen and item[1] != source:
            seen.add(item[1])
            unique.append(item)
    return unique[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'arch'), 'order': 60}  # the registry: no caller wiring (registry.py)
