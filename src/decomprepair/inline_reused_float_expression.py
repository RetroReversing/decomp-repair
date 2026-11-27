"""Inline a float temporary reused only by adjacent assignment/use pairs.

An N64 draft reused one float local in two switch arms. Inlining its product into either following field store
improved one KMC GCC 2.7.2 O1 diagnostic from 825 to 745 and O2 from 46,355 to 45,975. One function, not a match.
Every mention of the local must belong to an adjacent assignment/use pair, and the expression and store must have
no calls or writes other than known field reads and the final field store.
"""
import re

from .csource import find
from .integer_repair_support import IDENT, edit, view
from .shared_float_equality_ladder import _MACRO

FAMILY = 'inline_reused_float_expression'
FAMILIES = (FAMILY,)
_PAIR = re.compile(rf'(?m)^[ \t]*(?P<local>{IDENT})\s*=\s*(?P<expr>[^;{{}}\n]+);[ \t]*\n'
                   rf'[ \t]*(?P<consumer>M2C_FIELD\([^;{{}}\n]+;)', re.M)


def variants(source, name, header=''):
    part, span = view(source, name), find(source, name)
    macros = source + '\n' + (header or '')
    if not part or not span or not _MACRO.search(macros) or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean[span[0]:part.end]):
        return []
    if re.search(r'\btypedef\b[^;]*\bvolatile\b[^;]*\bf32\s*;|(?m:^\s*#\s*(?:define|undef)\s+f32\b)', macros):
        return []
    groups = {}
    for hit in _PAIR.finditer(part.clean, part.opening + 1, part.end):
        local, expr, consumer = hit['local'], hit['expr'], hit['consumer']
        if len(re.findall(r'\b' + re.escape(local) + r'\b', consumer)) != 1 or re.search(r'\b' + re.escape(local) + r'\b', expr):
            continue
        if (re.search(r'\+\+|--|(?<![<>=!])=(?!=)', expr) or re.search(r'\+\+|--', consumer)
                or len(re.findall(r'(?<![<>=!])=(?!=)', consumer)) != 1):
            continue
        if set(re.findall(r'\b(' + IDENT + r')\s*\(', expr + ' ' + consumer)) - {'M2C_FIELD'}:
            continue
        names = set(re.findall(r'\b' + IDENT + r'\b', expr + ' ' + consumer)) - {'M2C_FIELD'}
        if any(re.search(r'(?m)^\s*#\s*(?:define|undef)\s+' + re.escape(n) + r'\b', macros) for n in names):
            continue
        if not re.match(r'M2C_FIELD\(.*\)\s*=(?!=)', consumer):
            continue
        if re.search(r'/[*/]|#', source[hit.start():hit.end()]):
            continue
        groups.setdefault(local, []).append(hit)
    out = []
    for local, hits in groups.items():
        if len(re.findall(r'(?m)^\s*f32\s+' + re.escape(local) + r'\s*;', part.clean[part.opening:part.end])) != 1:
            continue
        if len(re.findall(r'\b' + re.escape(local) + r'\b', part.clean[part.opening:part.end])) != 1 + 2 * len(hits):
            continue
        if re.search(r'(?m)^\s*#\s*(?:define|undef)\s+' + re.escape(local) + r'\b', macros):
            continue
        for hit in hits:
            consumer = source[hit.start('consumer'):hit.end('consumer')]
            expr = source[hit.start('expr'):hit.end('expr')]
            consumer = re.sub(r'\b' + re.escape(local) + r'\b', lambda _, value=expr: f'((f32) ({value}))', consumer)
            pad = re.match(r'[ \t]*', source[hit.start():hit.end()])[0]
            out.append((FAMILY, edit(source, [(hit.start(), hit.end(), pad + consumer)])))
            if len(out) >= 8:
                return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}
