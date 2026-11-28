"""Vary the weight of a pointer-offset assignment for old MIPS register allocation.

One-shot scopes preserve the assignment but change GCC's loop-weighted reference counts. In an audio dispatcher,
four extra scopes on a pointer copy improved 2094 to 2049 where one, two and three extra scopes tied.
"""
import re

from .csource import _blank, find

FAMILY = 'pointer_weight_ladder'
IDENT = r'[A-Za-z_]\w*'
ASSIGN = re.compile(r'\b(' + IDENT + r')\s*=\s*(' + IDENT + r')\s*\+\s*(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*\s*;')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    body = clean[span[0]:span[1]]
    out = []
    for match in ASSIGN.finditer(body):
        target, base = match.group(1, 2)
        if body[:match.start()].rstrip()[-1:] not in ('{', '}', ';', ':'):
            continue
        # The destination is an ordinary declared pointer, not an object reached through an alias or volatile access.
        decl = re.compile(r'(?m)^\s*(?:void|char|s8|u8|s16|u16|s32|u32)\s*\*\s*' + re.escape(target) + r'\s*;')
        if not decl.search(body) or target == base:
            continue
        start, end = span[0] + match.start(), span[0] + match.end()
        statement = source[start:end]
        for depth in range(2, 7):
            wrapped = 'do { ' * depth + statement + ' } while (0);' * depth
            out.append((FAMILY, source[:start] + wrapped + source[end:]))
    return out


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
