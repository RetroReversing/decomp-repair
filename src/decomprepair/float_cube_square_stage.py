"""Stage the square in a cubic float expression.

A KMC GCC 2.7.2 O1 function kept the square and cube in different registers. Writing the square as a float local
changed its diagnostic score from 60 to 50; subsequent changes matched exactly. This preserves the multiplication
order, and requires plain, distinct nonvolatile float locals and target float multiply instructions.
"""
import re

from .csource import find
from .integer_repair_support import IDENT, edit, view

FAMILY = 'float_cube_square_stage'
FAMILIES = (FAMILY,)
_CUBE = re.compile(rf'(?m)^(?P<pad>[ \t]*)(?P<dst>{IDENT})\s*=\s*(?P<src>{IDENT})\s*\*\s*(?P=src)\s*\*\s*(?P=src)\s*;')


def variants(source, name, asm, header=''):
    if len(re.findall(r'\bmul\.s\b', asm or '')) < 2:
        return []
    part, span = view(source, name), find(source, name)
    macros = source + '\n' + (header or '')
    if not part or not span or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean[span[0]:part.end]):
        return []
    if re.search(r'\btypedef\b[^;]*\bvolatile\b[^;]*\bf32\s*;|(?m:^\s*#\s*(?:define|undef)\s+f32\b)', macros):
        return []
    fresh = 'repair_float_square'
    while re.search(r'\b' + fresh + r'\b', macros):
        fresh += '_'
    out = []
    for hit in _CUBE.finditer(part.clean, part.opening + 1, part.end):
        src, dst, pad = hit['src'], hit['dst'], hit['pad']
        if src == dst or any(len(re.findall(r'(?m)^\s*f32\s+' + re.escape(n) + r'\s*;', part.clean[part.opening:part.end])) != 1
                             or re.search(r'(?m)^\s*#\s*(?:define|undef)\s+[^\n]*\b' + re.escape(n) + r'\b', macros)
                             for n in (src, dst)):
            continue
        text = f'{pad}{fresh} = {src} * {src};\n{pad}{dst} = {fresh} * {src};'
        out.append((FAMILY, edit(source, [(part.opening + 1, part.opening + 1, f'\n    f32 {fresh};'),
                                         (hit.start(), hit.end(), text)])))
    return out[:8]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'header'), 'archs': ('mips',)}
