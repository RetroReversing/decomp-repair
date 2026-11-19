"""A pointer moved back by a constant, held in a local before the sum it is part of.

m2c writes `i + (p - 0x115)` where the game computed `p - 0x115` first and then added the index; gcc 2.7.2 reassociates
the written sum to `(i - 0x115) + p`, one register off. An N64 function was 99.9% that way (after
`symbol_address_local` gave `p` its local) and exact with `q = p - 0x115;` before the statement and `i + q` in it. The
value is the same; only where gcc does the subtraction changes.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'offset_base_local'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)'
SUM = re.compile(r'(?P<left>' + IDENT + r')\s*\+\s*\(\s*(?P<base>' + IDENT + r')\s*-\s*(?P<k>' + NUMBER + r')\s*\)'
                 r'|\(\s*(?P<base2>' + IDENT + r')\s*-\s*(?P<k2>' + NUMBER + r')\s*\)\s*\+\s*(?P<right>' + IDENT + r')')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or '__repair_offset' in clean[opening:end]:
        return []
    result = []
    for hit in SUM.finditer(clean, opening, end):
        base = hit['base'] or hit['base2']
        k = hit['k'] or hit['k2']
        other = hit['left'] or hit['right']
        # the base must be a pointer local declared in the function
        declared = re.search(r'(?m)^[ \t]*(?P<type>(?:const\s+)?[A-Za-z_]\w*(?:\s+[A-Za-z_]\w*)?)\s*\*\s*'
                             + re.escape(base) + r'\s*;', clean[opening:end])
        if not declared:
            continue
        line = clean.rfind('\n', opening, hit.start()) + 1
        statement = clean[line:clean.find(';', hit.end()) + 1]
        # a plain assignment statement: a new statement can't go in front of a loop header or a condition
        if re.match(r'\s*(?:for|while|if|do|return|switch|else)\b', statement) or not re.search(r'[^=!<>]=(?!=)', statement):
            continue
        indent = re.match(r'[ \t]*', source[line:])[0]
        kind = ' '.join(declared['type'].split())
        decl_at = opening + declared.end()
        text = (source[:decl_at] + f'\n    {kind} *__repair_offset;' + source[decl_at:line]
                + f'{indent}__repair_offset = {base} - {k};\n'
                + source[line:hit.start()] + f'{other} + __repair_offset' + source[hit.end():])
        if text not in [t for _, t in result]:
            result.append((FAMILY, text))
        if len(result) >= 3:
            break
    return result
