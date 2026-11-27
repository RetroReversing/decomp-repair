"""Move a float-local constant initialization past a call that cannot access the local.

A KMC GCC 2.7.2 function's constant sat after a trigonometric call in the target, while a draft initialized it before
the call. Moving it after the call improved the O1 diagnostic score 745 -> 565 without changing the O2 score 45,975.
This is one function observation, not a match. The local must be a plain, unescaped float absent from the call line.
"""
import re

from .csource import find
from .integer_repair_support import IDENT, edit, view

FAMILY = 'sink_float_constant_past_call'
FAMILIES = (FAMILY,)
_PAIR = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<local>{IDENT})\s*=\s*[-+]?\d+\.\d*[fF]\s*;[ \t]*\n'
                   rf'(?P<callline>[ \t]*{IDENT}\s*=\s*[^;{{}}\n]*\b{IDENT}\s*\([^;{{}}\n]*;)')


def variants(source, name, header=''):
    part, span = view(source, name), find(source, name)
    macros = source + '\n' + (header or '')
    if not part or not span or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean[span[0]:part.end]):
        return []
    if re.search(r'\btypedef\b[^;]*\bvolatile\b[^;]*\bf32\s*;|(?m:^\s*#\s*(?:define|undef)\s+f32\b)', macros):
        return []
    out = []
    for hit in _PAIR.finditer(part.clean, part.opening + 1, part.end):
        local = hit['local']
        if (len(re.findall(r'(?m)^\s*f32\s+' + re.escape(local) + r'\s*;', part.clean[part.opening:part.end])) != 1
                or re.search(r'&\s*\(*\s*' + re.escape(local) + r'\b', part.clean[span[0]:part.end])
                or re.search(r'\b' + re.escape(local) + r'\b', hit['callline'])
                or re.search(r'(?m)^\s*#\s*(?:define|undef)\s+[^\n]*\b' + re.escape(local) + r'\b', macros)
                or re.search(r'/[*/]|#', source[hit.start():hit.end()])):
            continue
        first = source[hit.start():hit.start('callline')].rstrip()
        second = source[hit.start('callline'):hit.end()]
        out.append((FAMILY, edit(source, [(hit.start(), hit.end(), second + '\n' + first)])))
    return out[:8]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
