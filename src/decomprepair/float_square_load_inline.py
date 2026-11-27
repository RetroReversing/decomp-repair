"""Inline two adjacent float field snapshots used only to square and add them.

m2c may write `x = field0; y = field1; z = x*x + y*y;`. For one large N64 function, writing those nonvolatile
fields directly in the sum changed KMC GCC 2.7.2's load order under `-G0 -mips3 -mgp32 -mfp32 -O1`: the diagnostic
score improved 9,910 -> 9,760. The -O2 profile produced the same instructions either way. This is one observation,
not a match. Offer each pair separately; two otherwise independent changes can affect allocation together.
"""
import re

from .csource import find
from .integer_repair_support import IDENT, NUMBER, edit, view

FAMILY = 'float_square_load_inline'
FAMILIES = (FAMILY,)
LIMIT = 8

_PAIR = re.compile(
    rf'(?m)^[ \t]*(?P<x>{IDENT})\s*=\s*(?P<a>M2C_FIELD\(\s*(?P<base>{IDENT})\s*,\s*f32\s*\*\s*,\s*{NUMBER}\s*\))\s*;\s*'
    rf'(?P<y>{IDENT})\s*=\s*(?P<b>M2C_FIELD\(\s*(?P=base)\s*,\s*f32\s*\*\s*,\s*{NUMBER}\s*\))\s*;\s*'
    rf'(?P<dest>{IDENT})\s*=\s*\(\s*(?P=x)\s*\*\s*(?P=x)\s*\)\s*\+\s*\(\s*(?P=y)\s*\*\s*(?P=y)\s*\)\s*;'
)
_MACRO = re.compile(r'(?m)^\s*#\s*define\s+M2C_FIELD\(expr,\s*type_ptr,\s*offset\)\s*'
                    r'\(\*\(type_ptr\)\(\(s8\s*\*\)\(expr\)\s*\+\s*\(offset\)\)\)[ \t]*$')


def variants(source, name, asm, header=''):
    if not re.search(r'\blwc1\b', asm or '') or not re.search(r'\bmul\.s\b', asm or ''):
        return []
    part = view(source, name)
    span = find(source, name)
    if not part or not span or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean[span[0]:part.end]):
        return []
    macros = source + '\n' + (header or '')
    if (len(re.findall(r'(?m)^\s*#\s*(?:define|undef)\s+M2C_FIELD\b', macros)) != 1 or not _MACRO.search(macros)
            or re.search(r'\btypedef\b[^;]*\bvolatile\b[^;]*\bf32\s*;', macros)
            or re.search(r'(?m)^\s*#\s*(?:define|undef)\s+f32\b', macros)):
        return []
    out = []
    for hit in _PAIR.finditer(part.clean, part.opening + 1, part.end):
        x, y = hit['x'], hit['y']
        if x == y or re.search(r'/[*/]|#', source[hit.start():hit.end()]):
            continue
        decls = []
        for local in (x, y):
            decl = list(re.finditer(rf'(?m)^[ \t]*f32\s+{re.escape(local)}\s*;[ \t]*\n', part.clean[part.opening:part.end]))
            if (len(decl) != 1 or len(re.findall(rf'\b{re.escape(local)}\b', part.body)) != 4
                    or re.search(rf'(?m)^\s*#\s*define[^\n]*\b{re.escape(local)}\b', macros)):
                break
            decls.append((part.opening + decl[0].start(), part.opening + decl[0].end(), ''))
        if len(decls) != 2:
            continue
        a = source[slice(*hit.span('a'))]
        b = source[slice(*hit.span('b'))]
        indent = re.match(r'[ \t]*', source[hit.start():hit.end()])[0]
        replacement = f'{indent}{hit["dest"]} = ({a} * {a}) + ({b} * {b});'
        out.append((FAMILY, edit(source, decls + [(hit.start(), hit.end(), replacement)])))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'header'), 'archs': ('mips',)}
