"""Initialize a selected float before conditionally negating it and copying it back.

A KMC GCC 2.7.2 O1 function's final three differing rows were the register holding a conditional float negation.
Initializing the selection from its input and negating the selection on the non-positive path reached exact bytes
(15 -> 0). Both spellings select -x when x is unordered or zero, preserving signed zero and NaNs. Plain nonvolatile
float locals and target compare/branch/negate evidence are required.
"""
import re

from .csource import find
from .integer_repair_support import IDENT, edit, view

FAMILY = 'copyback_float_negation'
FAMILIES = (FAMILY,)
_PATTERN = re.compile(
    rf'(?m)^(?P<pad>[ \t]*)if\s*\(\s*(?P<src>{IDENT})\s*>\s*0\.0[fF]\s*\)\s*\{{\s*'
    rf'(?P<dst>{IDENT})\s*=\s*(?P=src)\s*;\s*\}}\s*else\s*\{{\s*'
    rf'(?P=dst)\s*=\s*-\s*(?P=src)\s*;\s*\}}\s*(?P=src)\s*=\s*(?P=dst)\s*;'
)


def variants(source, name, asm, header=''):
    if not all(re.search(pattern, asm or '') for pattern in (r'\bc\.lt\.s\b', r'\bbc1t\b', r'\bneg\.s\b', r'\bmov\.s\b')):
        return []
    part, span = view(source, name), find(source, name)
    macros = source + '\n' + (header or '')
    if not part or not span or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean[span[0]:part.end]):
        return []
    if re.search(r'\btypedef\b[^;]*\bvolatile\b[^;]*\bf32\s*;|(?m:^\s*#\s*(?:define|undef)\s+f32\b)', macros):
        return []
    out = []
    for hit in _PATTERN.finditer(part.clean, part.opening + 1, part.end):
        src, dst, pad = hit['src'], hit['dst'], hit['pad']
        if src == dst or re.search(r'/[*/]|#', source[hit.start():hit.end()]):
            continue
        if any(len(re.findall(r'(?m)^\s*f32\s+' + re.escape(n) + r'\s*;', part.clean[part.opening:part.end])) != 1
               or re.search(r'(?m)^\s*#\s*(?:define|undef)\s+[^\n]*\b' + re.escape(n) + r'\b', macros) for n in (src, dst)):
            continue
        text = (f'{pad}{dst} = {src};\n{pad}if (!({src} > 0.0f)) {{ {dst} = -{dst}; }}\n'
                f'{pad}{src} = {dst};')
        out.append((FAMILY, edit(source, [(hit.start(), hit.end(), text)])))
    return out[:8]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'header'), 'archs': ('mips',)}
