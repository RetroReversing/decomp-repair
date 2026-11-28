"""Vary a switch's GCC allocation weight with one-shot scopes.

Old MIPS GCC weights references by loop depth. A controller dispatch in an audio handler scored 881, then 846 with
six one-shot scopes around its switch. Its `break` statements still leave the switch; `continue` and jumps need
special care and are excluded.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'switch_weight_ladder'
SWITCH = re.compile(r'\bswitch\s*\(')
LIMIT = 64


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    body = clean[span[0]:span[1]]
    if re.search(r'\b(?:goto|asm|__asm__|setjmp|longjmp)\b|^\s*#', body, re.M):
        return []
    out = []
    for found in SWITCH.finditer(clean, span[0], span[1]):
        cond_end = close(clean, found.end() - 1)
        brace = cond_end and re.match(r'\s*\{', clean[cond_end:span[1]])
        if not brace:
            continue
        opening = cond_end + brace.end() - 1
        end = close(clean, opening, '{', '}')
        if not end or end > span[1] or re.search(r'\bcontinue\b', clean[opening:end]):
            continue
        switch = source[found.start():end]
        for depth in range(2, 9):
            wrapped = 'do { ' * depth + switch + ' } while (0);' * depth
            out.append((FAMILY, source[:found.start()] + wrapped + source[end:]))
            if len(out) >= LIMIT:
                return out
    return out


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
