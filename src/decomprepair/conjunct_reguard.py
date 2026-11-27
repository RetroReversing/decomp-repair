"""`if (a && v < 0) { switch (v) ...` with the last test of the condition written again before the switch.

The game's code can test a value that the enclosing `&&` already tested: the target keeps a `bgez` in front of a
switch's compare tree that no case list gives. A 169-instruction N64 state function (`gcc-2.7.2-kmc -O1`) had it, and
writing the guard moved a candidate from 725 to 365 (a controlled result of one function). The guard repeats a test
that is already known true, so the program is unchanged. Only a side-effect-free last conjunct of a top-level `&&`,
in a block whose only statement is a `switch` on a name the conjunct reads. A candidate rewrite; the judge decides.
"""
import re

from .integer_repair_support import IDENT, view
from .pattern_repairs import close

FAMILY = 'conjunct_reguard'
FAMILIES = (FAMILY,)
LIMIT = 8


def _last_conjunct(condition):
    """The text after the last top-level `&&`, or None (also for a top-level `||` or `?`, which bind looser)."""
    depth, last = 0, None
    for hit in re.finditer(r'[()\[\]]|&&|\|\||\?', condition):
        token = hit[0]
        depth += token in '(['
        depth -= token in ')]'
        if depth:
            continue
        if token in ('||', '?'):
            return None
        if token == '&&':
            last = hit.end()
    return None if last is None else (last, len(condition))


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, out = part.clean, []
    for hit in re.finditer(r'\bif\s*\(', clean[part.opening:part.end]):
        paren = part.opening + hit.end() - 1
        cond_end = close(clean, paren)
        block = re.compile(r'\s*\{\s*').match(clean, cond_end) if cond_end else None
        if not block:
            continue
        switch = re.compile(rf'switch\s*\(\s*(?P<name>{IDENT})\s*\)').match(clean, block.end())
        span = _last_conjunct(clean[paren + 1:cond_end - 1]) if switch else None
        if not span:
            continue
        guard = source[paren + 1 + span[0]:paren + 1 + span[1]].strip()
        if re.search(rf'\+\+|--|(?<![=!<>])=(?!=)|\b{IDENT}\s*\(', guard) \
                or not re.search(rf'(?<![\w.>]){switch["name"]}\b', guard):
            continue
        body = re.compile(r'\s*\{').match(clean, close(clean, clean.index('(', switch.start()), '(', ')'))
        stop = close(clean, body.end() - 1, '{', '}') if body else None
        if not stop or not re.compile(r'\s*\}').match(clean, stop):
            continue
        out.append((FAMILY, source[:block.end()] + f'if ({guard}) ' + source[block.end():]))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 101}  # the registry: no caller wiring (registry.py)
