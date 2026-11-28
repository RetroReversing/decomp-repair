"""Swap independent assignments to a fresh local record in a comma-expression guard.

A MIPS audio dispatcher's two configuration stores in a short-circuit guard improved 2049 to 1989 when reordered.
Only a plain local struct whose address has not escaped can be treated as independent of the other value's loads.
"""
import re

from .csource import _blank, find
from .independent_statement_swap import independent
from .pattern_repairs import close

FAMILY = 'record_comma_order'
IDENT = r'[A-Za-z_]\w*'
START = re.compile(r'\b(?P<obj>' + IDENT + r')\.(?P<first>' + IDENT + r')\s*=\s*'
                   r'(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*\s*,\s*'
                   r'(?P<second>(?P=obj)\.(?P<field>' + IDENT + r')\s*=\s*'
                   r'(?:\(\s*(?:s8|u8|s16|u16|s32|u32|int)\s*\)\s*)?\()')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    body = clean[span[0]:span[1]]
    out = []
    for match in START.finditer(body):
        obj = match['obj']
        declaration = re.compile(r'\bstruct\s*\{(?P<fields>[^{}]*)\}\s+' + re.escape(obj) + r'\s*;')
        records = list(declaration.finditer(body[:match.start()]))
        if (len(records) != 1 or match['first'] == match['field']
                or re.search(r'\b(?:volatile|union)\b|:', records[0]['fields'])
                or re.search(r'&\s*\(*\s*' + re.escape(obj) + r'\b', body[:match.start()])
                or re.search(r'\bunion\s*\{[^{}]*\}\s+' + re.escape(obj) + r'\s*;', body)
                or re.search(r'\b' + IDENT + r'\s+' + re.escape(obj) + r'\s*;', body)):
            continue
        names = re.findall(r'\b(?:s8|u8|s16|u16|s32|u32|int|char|short)\s+(' + IDENT + r')\s*;', records[0]['fields'])
        if names.count(match['first']) != 1 or names.count(match['field']) != 1:
            continue
        end = close(body, match.end() - 1)
        if not end or not re.match(r'\s*[,)]', body[end:]):
            continue
        comma = body.find(',', match.start(), match.start('second'))
        first = body[match.start():comma].strip()
        second = body[match.start('second'):end].strip()
        if not independent(first + ';', second + ';'):
            continue
        a, mid, last = span[0] + match.start(), span[0] + match.start('second'), span[0] + end
        prefix = source[a:span[0] + comma]
        separator = source[span[0] + comma:mid]
        out.append((FAMILY, source[:a] + source[mid:last] + separator + prefix + source[last:]))
    return out


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
