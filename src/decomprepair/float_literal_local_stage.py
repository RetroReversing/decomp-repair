"""Hold a float multiplier in the result local before a multiply/divide expression.

A KMC GCC 2.7.2 function used the result register for a float constant load before multiplying and dividing.
Staging that constant in the result local in both arms improved the O1 diagnostic 565 -> 545 and O2 45,975 ->
45,965. This is one function observation, not a match. The result and operand must be distinct unescaped floats.
"""
import re

from .csource import find
from .float_local_safety import unshadowed
from .integer_repair_support import IDENT, edit, view

FAMILY = 'float_literal_local_stage'
FAMILIES = (FAMILY,)
_PAIR = re.compile(rf'(?m)^(?P<pad>[ \t]*)(?P<dst>{IDENT})\s*=\s*\(\s*(?P<src>{IDENT})\s*\*\s*'
                   rf'(?P<factor>[-+]?\d+\.\d*[fF])\s*\)\s*/\s*(?P<div>[-+]?\d+\.\d*[fF])\s*;')


def variants(source, name, header=''):
    part, span = view(source, name), find(source, name)
    macros = source + '\n' + (header or '')
    if not part or not span or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean[span[0]:part.end]):
        return []
    if re.search(r'\btypedef\b[^;]*\bvolatile\b[^;]*\bf32\s*;|(?m:^\s*#\s*(?:define|undef)\s+f32\b)', macros):
        return []
    groups = []
    by_shape = {}
    for hit in _PAIR.finditer(part.clean, part.opening + 1, part.end):
        dst, src = hit['dst'], hit['src']
        if not unshadowed(part.clean, part.opening, part.end, dst, src):
            continue
        if (dst == src or len(re.findall(r'(?m)^\s*f32\s+' + re.escape(dst) + r'\s*;', part.clean[part.opening:part.end])) != 1
                or len(re.findall(r'\bf32\s+' + re.escape(src) + r'\b', part.clean[span[0]:part.end])) != 1
                or any(re.search(r'&\s*\(*\s*' + re.escape(n) + r'\b', part.clean[span[0]:part.end])
                       or re.search(r'(?m)^\s*#\s*(?:define|undef)\s+[^\n]*\b' + re.escape(n) + r'\b', macros) for n in (dst, src))):
            continue
        pad = hit['pad']
        replacement = (f"{pad}{dst} = {hit['factor']};\n{pad}{dst} = ({src} * {dst}) / {hit['div']};")
        change = (hit.start(), hit.end(), replacement)
        groups.append(change)
        by_shape.setdefault((dst, src, hit['factor'], hit['div']), []).append(change)
        if len(groups) == 8:
            break
    out = [(FAMILY, edit(source, [change])) for change in groups]
    for same in by_shape.values():
        if len(same) > 1:
            out.append((FAMILY, edit(source, same)))
    if len(groups) > 1 and len(by_shape) > 1:
        out.append((FAMILY, edit(source, groups)))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}
