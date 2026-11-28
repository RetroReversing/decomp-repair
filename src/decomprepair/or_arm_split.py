"""An `if (a || b)` written as two arms with the same body: `if (a) S else if (b) S`.

GCC 2.7.2 folds `x == 0 || x == K` into `sltiu`, `xori`, `sltiu`, `or` and one branch over a single load. Where the
target branches on each test and loads `x` again for the second (`beqz $v0,L; lb $v1; bne $v1,$v0,M; L:`), the source
had two arms, which jump.c merges only after the fold would have happened. Any `else` that followed stays on the second
`if`, so both forms run the same statements. KMC GCC 2.7.2 -O1, a 119-instruction two-key lookup: 960 -> 0.

A `guard && (a || b ...)` with no `else` is split inside the guard: `if (guard) { if (a) S else if (b) S }`. Where
`S` ends in a `return`, loop.c moves each arm's copy out of the loop (a block with no label that ends in a jump out
of it) and jump2 merges the copies afterwards; the `||` form has a label in front of its one body, which stays in the
loop. SN GCC 2.8.1 `-O2`, a 435-instruction hit search: 1915 -> 470.

or_arm_split
    Each `if (a || b ...) { S }` (S short) on its own, every one of them together, and each pair of them as one child:
    a function often has one `||` the target keeps folded among several it splits (a 146-instruction N64 drawing
    function, `-O1`: two of three split, 1635 -> 415).
"""
import re
from itertools import combinations

from .c_scan import close
from .csource import _blank, find

FAMILY = 'or_arm_split'
FAMILIES = (FAMILY,)
LIMIT = 16
PAIRED = 5  # pairs are offered among the first five sites
BODY = 400  # a body longer than this is not copied
_IF = re.compile(r'\bif\s*\(')
_KEPT = re.compile(r'\b(?:case|default|static)\b|\b[A-Za-z_]\w*\s*:(?!:)\s*[^;?]*;')


def _operands(condition):
    """The operands of the condition's top-level `||`, as (start, end) offsets into it."""
    spans, depth, begin, at = [], 0, 0, 0
    while at < len(condition):
        char = condition[at]
        depth += (char in '([') - (char in ')]')
        if depth == 0 and condition.startswith('||', at):
            spans.append((begin, at))
            begin = at + 2
            at += 1
        elif depth == 0 and char in '?,':
            return []
        at += 1
    return spans + [(begin, len(condition))] if spans else []


def _sites(source, clean, lo, hi):
    """(start, end, replacement) for each `if` of an `||` with a braced body that can be written twice."""
    sites = []
    for m in _IF.finditer(clean, lo, hi):
        end = close(clean, m.end() - 1, '(', ')')
        if end < 0:
            continue
        opening = end + 1 + len(clean[end + 1:hi]) - len(clean[end + 1:hi].lstrip())
        if not clean.startswith('{', opening):
            continue
        tail = close(clean, opening)
        if tail < 0 or tail - opening > BODY or _KEPT.search(clean, opening, tail):
            continue
        condition = clean[m.end():end]
        spans = _operands(condition)
        body = source[opening:tail + 1]
        if spans:
            arms = [f'if ({source[m.end() + a:m.end() + b].strip()}) {body}' for a, b in spans]
            sites.append((m.start(), tail + 1, ' else '.join(arms)))
            continue
        group = _guarded_group(condition)
        if not group or clean[tail + 1:hi].lstrip().startswith('else'):
            continue  # an `else` runs when the guard fails too, which the nested form would lose
        guard, base, spans = group
        arms = [f'if ({source[m.end() + base + a:m.end() + base + b].strip()}) {body}' for a, b in spans]
        outer = source[m.end():m.end() + guard].strip()
        sites.append((m.start(), tail + 1, f'if ({outer}) {{ {" else ".join(arms)} }}'))
    return sites


def _guarded_group(condition):
    """`guard && (a || b ...)`: (where the guard ends, where the group's inside starts, its operands), or None."""
    stripped = condition.rstrip()
    if not stripped.endswith(')'):
        return None
    depth, at, opened, guard = 0, 0, None, None
    while at < len(stripped):
        char = stripped[at]
        if depth == 0 and (condition.startswith('||', at) or char in '?,'):
            return None
        if depth == 0 and condition.startswith('&&', at):
            guard, opened = at, None
            at += 2
            continue
        if char == '(' and depth == 0 and guard is not None and not stripped[guard + 2:at].strip():
            opened = at
        depth += (char in '([') - (char in ')]')
        if depth == 0 and char == ')' and opened is not None and at != len(stripped) - 1:
            opened = None
        at += 1
    if guard is None or opened is None:
        return None
    spans = _operands(stripped[opened + 1:-1])
    return (guard, opened + 1, spans) if spans else None


def _apply(source, sites):
    for start, end, text in reversed(sites):
        source = source[:start] + text + source[end:]
    return source


def variants(source, name):
    span = find(source, name)
    if not span or '||' not in source:
        return []
    clean = _blank(source)
    sites = _sites(source, clean, span[0], span[1])
    apart = []  # sites outside each other, so that all of them can be written at once
    for site in sites:
        if not apart or site[0] >= apart[-1][1]:
            apart.append(site)
    pairs = [list(pair) for pair in combinations(sites[:PAIRED], 2) if pair[0][1] <= pair[1][0] and list(pair) != apart]
    picks = ([apart] if len(apart) > 1 else []) + [[site] for site in sites] + pairs
    return [(FAMILY, _apply(source, pick)) for pick in picks[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
