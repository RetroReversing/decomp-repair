"""A local given one constant and overwritten with another under a test, written as the `?:` it came from.

    t = 0.4f;
    if (!(x <= 0.0002f) | !(x >= (-0.0002f))) { t = 0.1f; }

as `t = (!(x <= 0.0002f) | !(x >= (-0.0002f))) ? 0.1f : 0.4f;`. GCC 2.7.2 expands a `?:` whose arms are constants by
computing the condition first and then loading the default arm's constant in the block of the branch (the target's
`lui`/`mtc1` of 0.4 sits after both compares, right before the `beqz`), where the assignment written first is
emitted before the condition and the first scheduler hoists its load into the compare's block. Two such selections in
a 1300-instruction KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) controller routine: 1245 -> 610 in the isolated judge
with both rewritten (one child). `conditional_ternary` reads only a selection that is then returned or stored at once;
this one keeps the local, which is read later.

guarded_constant_ternary
    `V = A;` directly followed by `if (C) { V = B; }` (braced or not, no `else`), A and B numeric literals (integer or
    float), C free of assignments, increments and V: one `V = (C) ? B : A;`. Every site together first, then each.

Hypothesis from the match (where expr.c puts the default arm's constant was read off the target, not the compiler's
source). The exact judge decides every child."""
import re

from .csource import _blank, find

FAMILY = 'guarded_constant_ternary'
FAMILIES = (FAMILY,)
LIMIT = 6
IDENT = r'[A-Za-z_]\w*'
LITERAL = r'\(?\s*-?\s*(?:0[xX][0-9a-fA-F]+[uUlL]*|\d+\.\d*(?:[eE][-+]?\d+)?[fF]?|\.\d+[fF]?|\d+[uUlLfF]*)\s*\)?'


def _span(source, name):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    head = re.search(r'\b' + re.escape(name) + r'\s*\([^{};]*\)\s*{', clean[span[0]:span[1]])
    return (span[0] + head.end() - 1, span[1]) if head else None


def _condition_end(text, start):
    depth = 0
    for j in range(start, len(text)):
        if text[j] == '(':
            depth += 1
        elif text[j] == ')':
            depth -= 1
            if depth == 0:
                return j + 1
    return None


def _sites(source, name):
    span = _span(source, name)
    if not span:
        return []
    clean = _blank(source)
    head = re.compile(rf'^(?P<indent>[ \t]*)(?P<var>{IDENT})\s*=\s*(?P<a>{LITERAL})\s*;[ \t]*\n[ \t]*if\s*(?=\()', re.M)
    out = []
    for hit in head.finditer(clean, span[0], span[1]):
        var = hit['var']
        cond_end = _condition_end(clean, hit.end())
        if cond_end is None:
            continue
        cond = source[hit.end() + 1:cond_end - 1].strip()
        if re.search(r'\+\+|--|[^=!<>]=(?!=)', cond) or re.search(rf'(?<![\w.>]){re.escape(var)}\b', cond):
            continue
        body = re.compile(rf'\s*(?:{{\s*{re.escape(var)}\s*=\s*(?P<b1>{LITERAL})\s*;\s*}}|{re.escape(var)}\s*=\s*(?P<b2>{LITERAL})\s*;)[ \t]*\n?')
        m = body.match(clean, cond_end)
        if not m:
            continue
        if re.match(r'\s*else\b', clean[m.end():]):
            continue
        b = (m['b1'] or m['b2']).strip()
        text = f"{hit['indent']}{var} = ({cond}) ? {b} : {hit['a'].strip()};\n"
        out.append((hit.start(), m.end(), text))
    return out


def variants(source, name):
    sites = _sites(source, name)
    out = []
    if len(sites) > 1:
        child = source
        for start, end, text in sorted(sites, reverse=True):
            child = child[:start] + text + child[end:]
        out.append((FAMILY, child))
    for start, end, text in sites:
        out.append((FAMILY, source[:start] + text + source[end:]))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
