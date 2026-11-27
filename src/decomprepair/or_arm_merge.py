"""`if (a) S else if (b) S` written as the `if (a || b) S` the game had: the other direction of `or_arm_split`.

m2c writes a test the compiler branched on twice as two arms with the same body. GCC 2.7.2 does not give the same code:
with two arms each assigns the value and jumps on its own, while `a || b` reaches one body from two tests, so the code
after it starts at a label and a global compared again is loaded again. A KMC 2.7.2 `-O1` function that picks a
direction from a float angle (`== 0.0f || == 360.0f`, four times over) had been held at 1550 with the global declared
`volatile` to get those reloads: merging the arms alone or dropping `volatile` alone scored the same 1550, both together
were byte-identical. Hence the second child, which does both.

or_arm_merge
    Every run of equal arms written as one `||`, all at once and then each run alone.
or_arm_merge_plain
    All of them, with every `extern volatile` scalar of the source declared plain.
"""
import re

from .c_scan import close
from .csource import _blank, find

FAMILY = 'or_arm_merge'
PLAIN_FAMILY = 'or_arm_merge_plain'
FAMILIES = (FAMILY, PLAIN_FAMILY)
LIMIT = 8
_IF = re.compile(r'\bif\s*\(')
_ELSE_IF = re.compile(r'\s*else\s+if\s*\(')
_KEPT = re.compile(r'\b(?:case|default|static|if|else|for|while|do|switch)\b|\b[A-Za-z_]\w*\s*:(?!:)\s*[^;?]*;')
_LOOSE = re.compile(r'\?|(?<![=!<>])=(?!=)|,(?![^()]*\))')  # an operand that would bind differently beside `||`
_VOLATILE = re.compile(r'(?m)^([ \t]*extern\s+(?:[\w]+\s+)*?)volatile\s+((?:[\w]+\s+)*[\w]+\s*;)')


def _arm(clean, paren, limit):
    """(condition start, condition end, body start, body end) of the `if` whose `(` is at `paren`, or None."""
    end = close(clean, paren, '(', ')')
    if end < 0:
        return None
    body = end + 1
    while body < limit and clean[body].isspace():
        body += 1
    if clean.startswith('{', body):
        tail = close(clean, body)
        inside = clean[body + 1:tail]
    else:
        tail = clean.find(';', body, limit)
        inside = clean[body:tail + 1]
    if tail < 0 or _KEPT.search(inside) or (not clean.startswith('{', body) and '{' in inside):
        return None
    return paren + 1, end, body, tail + 1


def _sites(source, clean, lo, hi):
    """(start, end, replacement) for each run of arms with one body, outermost first and not overlapping."""
    sites, done = [], lo
    for match in _IF.finditer(clean, lo, hi):
        if match.start() < done:
            continue
        head = _arm(clean, match.end() - 1, hi)
        if not head:
            continue
        body = ' '.join(source[head[2]:head[3]].split())
        conditions, end = [source[head[0]:head[1]].strip()], head[3]
        while (other := _ELSE_IF.match(clean, end, hi)):
            arm = _arm(clean, other.end() - 1, hi)
            if not arm or ' '.join(source[arm[2]:arm[3]].split()) != body:
                break
            conditions.append(source[arm[0]:arm[1]].strip())
            end = arm[3]
        if len(conditions) == 1 or any(_LOOSE.search(_blank(c)) for c in conditions):
            continue
        joined = ' || '.join(f'({c})' if '&&' in c else c for c in conditions)
        sites.append((match.start(), end, f'if ({joined}) {source[head[2]:head[3]]}'))
        done = end
    return sites


def _apply(source, sites):
    for start, end, text in reversed(sites):
        source = source[:start] + text + source[end:]
    return source


def variants(source, name):
    span = find(source, name)
    if not span or 'else' not in source:
        return []
    sites = _sites(source, _blank(source), span[0], span[1])
    if not sites:
        return []
    merged = _apply(source, sites)
    result = [(FAMILY, merged)]
    plain = _VOLATILE.sub(r'\1\2', merged)
    if plain != merged:
        result.append((PLAIN_FAMILY, plain))
    if len(sites) > 1:
        result += [(FAMILY, _apply(source, [site])) for site in sites]
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
