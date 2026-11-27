"""Offer the opposite initialization order for a conditional float negation.

For a nonvolatile float local, `v = x; if (!(x > 0.0f)) v = -x;` has the same value as initializing `v = -x`
and assigning `x` only when it is positive (including signed zero and NaN). An N64 function's two such branches
scored 5,970 -> 5,705 and 5,880 separately, 5,615 together, under KMC GCC 2.7.2 -G0 -mips3 -mgp32 -mfp32 -O1;
the second alone also improved its recorded -O2 score 49,265 -> 49,170. One observation, not a match.
Only plain float locals and target assembly with a float comparison, branch and negation are offered; a judge
chooses whether the compiler's register and branch layout is closer.
"""
import re

from .csource import find
from .integer_repair_support import IDENT, edit, view

FAMILY = 'float_negation_branch_order'
FAMILIES = (FAMILY,)
LIMIT = 8
_PATTERN = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)(?P<dst>{IDENT})\s*=\s*(?P<src>{IDENT})\s*;[ \t]*\n'
    rf'[ \t]*if\s*\(\s*!\s*\(\s*(?P=src)\s*>\s*0\.0[fF]\s*\)\s*\)\s*\{{\s*'
    rf'(?P=dst)\s*=\s*-\s*(?P=src)\s*;\s*\}}'
)


def variants(source, name, asm, header=''):
    if not all(re.search(pattern, asm or '') for pattern in (r'\bc\.lt\.s\b', r'\bbc1t\b', r'\bneg\.s\b')):
        return []
    part, span = view(source, name), find(source, name)
    if not part or not span or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean[span[0]:part.end]):
        return []
    macros = source + '\n' + (header or '')
    if (re.search(r'\btypedef\b[^;]*\bvolatile\b[^;]*\bf32\s*;', macros)
            or re.search(r'(?m)^\s*#\s*(?:define|undef)\s+f32\b', macros)):
        return []
    edits = []
    for hit in _PATTERN.finditer(part.clean, part.opening + 1, part.end):
        dst, src = hit['dst'], hit['src']
        if dst == src or re.match(r'\s*else\b', part.clean[hit.end():part.end]):
            continue
        if re.search(r'/[*/]|#', source[hit.start():hit.end()]):
            continue
        if any(len(re.findall(rf'\bf32\s+{re.escape(var)}\s*;', part.clean[part.opening:part.end])) != 1
               or re.search(rf'(?m)^\s*#\s*(?:define|undef)\s+{re.escape(var)}\b', macros) for var in (dst, src)):
            continue
        indent = hit['indent']
        replacement = (f'{indent}{dst} = -{src};\n{indent}if ({src} > 0.0f) {{\n'
                       f'{indent}    {dst} = {src};\n{indent}}}')
        edits.append((hit.start(), hit.end(), replacement))
        if len(edits) >= LIMIT:
            break
    out = [(FAMILY, edit(source, [item])) for item in edits]
    if len(edits) > 1:
        out.append((FAMILY, edit(source, edits)))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'header'), 'archs': ('mips',)}
