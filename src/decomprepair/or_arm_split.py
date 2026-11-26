"""An `if (a || b)` written as two arms with the same body: `if (a) S else if (b) S`.

GCC 2.7.2 folds `x == 0 || x == K` into `sltiu`, `xori`, `sltiu`, `or` and one branch over a single load. Where the
target branches on each test and loads `x` again for the second (`beqz $v0,L; lb $v1; bne $v1,$v0,M; L:`), the source
had two arms, which jump.c merges only after the fold would have happened. Any `else` that followed stays on the second
`if`, so both forms run the same statements. KMC GCC 2.7.2 -O1, a 119-instruction two-key lookup: 960 -> 0.

or_arm_split
    Each `if (a || b ...) { S }` (S short) on its own, and every one of them together as one child.
"""
import re

from .c_scan import close
from .csource import _blank, find

FAMILY = 'or_arm_split'
FAMILIES = (FAMILY,)
LIMIT = 8
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
        spans = _operands(clean[m.end():end])
        if not spans:
            continue
        body = source[opening:tail + 1]
        arms = [f'if ({source[m.end() + a:m.end() + b].strip()}) {body}' for a, b in spans]
        sites.append((m.start(), tail + 1, ' else '.join(arms)))
    return sites


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
    picks = ([apart] if len(apart) > 1 else []) + [[site] for site in sites]
    return [(FAMILY, _apply(source, pick)) for pick in picks[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
