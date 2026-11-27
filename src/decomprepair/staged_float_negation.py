"""Stage a conditional float negation before assigning the result to its consumer.

A KMC GCC 2.7.2 function's target branches over a float negation and copies the selected value to another register.
Using a separate float local for the selected value before assigning the consumer improved an O1 diagnostic from
1,710 to 1,410; its O2 score was 46,375. This is one observation, not a match. Both branches preserve NaN and zero.
"""
import re

from .csource import find
from .float_local_safety import unshadowed
from .float_negation_branch_order import _EXPLICIT_ELSE
from .integer_repair_support import edit, view

FAMILY = 'staged_float_negation'
FAMILIES = (FAMILY,)


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
    for hit in _EXPLICIT_ELSE.finditer(part.clean, part.opening + 1, part.end):
        dst, src = hit['dst'], hit['src']
        if not unshadowed(part.clean, part.opening, part.end, dst, src):
            continue
        if dst == src or re.match(r'\s*else\b', part.clean[hit.end():part.end]) or re.search(r'/[*/]|#', source[hit.start():hit.end()]):
            continue
        if any(len(re.findall(rf'\bf32\s+{re.escape(var)}\s*;', part.clean[part.opening:part.end])) != 1
               or re.search(rf'(?m)^\s*#\s*(?:define|undef)\s+{re.escape(var)}\b', macros) for var in (dst, src)):
            continue
        local = 'repair_float_select'
        while re.search(r'\b' + local + r'\b', macros):
            local += '_'
        pad = hit['indent']
        replacement = (f'{pad}if ({src} > 0.0f) {{ {local} = {src}; }} else {{ {local} = -{src}; }}\n'
                       f'{pad}{dst} = {local};')
        out.append((FAMILY, edit(source, [(part.opening + 1, part.opening + 1, f'\n    f32 {local};'),
                                         (hit.start(), hit.end(), replacement)])))
    return out[:8]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'header'), 'archs': ('mips',)}
