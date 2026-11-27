"""Stage float field loads used in independent multiply/store arms.

Two arms of a KMC GCC 2.7.2 O1 function loaded a float, multiplied it by a local and an arm-specific constant,
and stored the result. Staging the field load in each arm fixed the multiplication operand order (25 -> 15); the
next repair matched the function exactly. Only the known field macro, plain locals and target float loads/multiplies
are accepted. Each site and all matching sites are offered.
"""
import re

from .csource import find
from .integer_repair_support import IDENT, edit, view
from .shared_float_equality_ladder import _MACRO

FAMILY = 'float_field_multiply_stage'
FAMILIES = (FAMILY,)
_FIELD = rf'M2C_FIELD\(\s*{IDENT}\s*,\s*f32\s*\*\s*,\s*(?:0[xX][0-9A-Fa-f]+|\d+)\s*\)'
_STORE = re.compile(rf'(?m)^(?P<pad>[ \t]*)(?P<out>{_FIELD})\s*=\s*(?P<field>{_FIELD})\s*\*\s*'
                    rf'(?P<local>{IDENT})\s*\*\s*(?P<const>[-+]?\d+\.\d*[fF])\s*;')


def variants(source, name, asm, header=''):
    if not re.search(r'\blwc1\b', asm or '') or not re.search(r'\bmul\.s\b', asm or ''):
        return []
    part, span = view(source, name), find(source, name)
    macros = source + '\n' + (header or '')
    if not part or not span or not _MACRO.search(macros) or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean[span[0]:part.end]):
        return []
    if re.search(r'\btypedef\b[^;]*\bvolatile\b[^;]*\bf32\s*;|(?m:^\s*#\s*(?:define|undef)\s+f32\b)', macros):
        return []
    fresh = 'repair_float_field'
    while re.search(r'\b' + fresh + r'\b', macros):
        fresh += '_'
    groups = {}
    for hit in _STORE.finditer(part.clean, part.opening + 1, part.end):
        local = hit['local']
        if (len(re.findall(r'(?m)^\s*f32\s+' + re.escape(local) + r'\s*;', part.clean[part.opening:part.end])) != 1
                or re.search(r'(?m)^\s*#\s*(?:define|undef)\s+[^\n]*\b' + re.escape(local) + r'\b', macros)
                or re.search(r'/[*/]|#', source[hit.start():hit.end()])):
            continue
        names = set(re.findall(r'\b' + IDENT + r'\b', hit['field'] + ' ' + hit['out'])) - {'M2C_FIELD'}
        if any(re.search(r'(?m)^\s*#\s*(?:define|undef)\s+' + re.escape(n) + r'\b', macros) for n in names):
            continue
        pad = hit['pad']
        replacement = (f"{pad}{fresh} = {hit['field']};\n{pad}{hit['out']} = {fresh} * {local} * {hit['const']};")
        groups.setdefault((hit['field'], hit['out'], local), []).append((hit.start(), hit.end(), replacement))
    out = []
    for changes in groups.values():
        options = [[change] for change in changes]
        if len(changes) > 1:
            options.append(changes)
        for option in options:
            out.append((FAMILY, edit(source, [(part.opening + 1, part.opening + 1, f'\n    f32 {fresh};')] + option)))
            if len(out) >= 12:
                return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'header'), 'archs': ('mips',)}
