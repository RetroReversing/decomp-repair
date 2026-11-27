"""A variable filled by both arms of an `if`/`else` (`if (c) { v = a; } else { v = b; }`), written as `v = c ? a : b;`.

The two spellings are one program, but gcc 2.7.2 does not build them alike. A hand-written absolute value
`if (t >= 0) { d = t; } else { d = -t; }` made `move $v0,$v1; bgez $v1; negu $v0,$v1` (the negation read from the
source); as `d = (t >= 0) ? t : -t;` it made the target's `move $v0,$v1; bgez $v1; negu $v0,$v0` (the conditional
expression is expanded into its target, so the `-t` arm negates the copy already made in the branch's delay slot).
Hypothesis from that one function's dumps, not confirmed in expr.c: an N64 function's two clamps (KMC 2.7.2 -O1 -g,
93 instructions) were 10 with the if/else and exact with both written this way.

The variable may be read later (unlike `ternary_argument`, which needs a single read in the next statement), and the
arms may be any expression without a top-level comma. Offered for every site at once, each site alone when there are
several, and each site with the test inverted and the arms exchanged.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close, negate

FAMILY = 'branch_choice_ternary'
FAMILIES = (FAMILY,)
LIMIT = 16

IDENT = r'[A-Za-z_]\w*'
IF = re.compile(r'\bif\s*\(')
THEN = re.compile(r'\s*\{\s*(?P<v>' + IDENT + r')\s*=(?!=)\s*(?P<e>[^;{}]+);\s*\}')
ELSE = re.compile(r'\s*else\s*\{\s*(?P<v>' + IDENT + r')\s*=(?!=)\s*(?P<e>[^;{}]+);\s*\}')
# (an `else if` after the else arm would make the `if` a chain this rewrite does not keep)
CHAIN = re.compile(r'\s*else\b')


def _top_level_comma(text):
    depth = 0
    for ch in text:
        if ch in '([':
            depth += 1
        elif ch in ')]':
            depth -= 1
        elif ch == ',' and depth == 0:
            return True
    return False


def _sites(source, clean, opening, end):
    sites = []
    for hit in IF.finditer(clean, opening, end):
        cond_open = hit.end() - 1
        cond_close = close(clean, cond_open)
        if not cond_close or cond_close > end:
            continue
        then = THEN.match(clean, cond_close)
        if not then:
            continue
        other = ELSE.match(clean, then.end())
        if not other or other['v'] != then['v'] or CHAIN.match(clean, other.end()):
            continue
        a = source[then.start('e'):then.end('e')].strip()
        b = source[other.start('e'):other.end('e')].strip()
        cond = source[cond_open + 1:cond_close - 1].strip()
        if not a or not b or not cond or _top_level_comma(a) or _top_level_comma(b):
            continue
        sites.append((hit.start(), other.end(), then['v'], cond, a, b))
    return sites


def _apply(source, edits):
    for start, stop, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[stop:]
    return source


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    sites = _sites(source, clean, opening, end)
    if not sites:
        return []
    plain = [(s, e, f'{v} = ({c}) ? {a} : {b};') for s, e, v, c, a, b in sites]
    out = [(FAMILY, _apply(source, plain))]
    if len(sites) > 1:
        out += [(FAMILY, _apply(source, [edit])) for edit in plain]
    for s, e, v, c, a, b in sites:
        inverse = negate(c)
        if inverse:
            out.append((FAMILY, _apply(source, [(s, e, f'{v} = ({inverse}) ? {b} : {a};')])))
    seen, unique = set(), []
    for family, child in out:
        if child != source and child not in seen:
            seen.add(child)
            unique.append((family, child))
    return unique[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
