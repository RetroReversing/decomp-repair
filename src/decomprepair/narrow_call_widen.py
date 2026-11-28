"""Keep a narrow call result in an int after explicitly narrowing it.

A narrow local and a wide local holding the same explicitly converted value have the same promoted value on reads,
but old MIPS GCC can schedule the narrowing differently. An audio dispatcher improved from 2481 to 2386.
"""
import re

from .csource import _blank, find

FAMILY = 'narrow_call_widen'
IDENT = r'[A-Za-z_]\w*'
DECL = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<kind>s16|u16|s8|u8)[ \t]+(?P<name>' + IDENT + r')[ \t]*;')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    body = clean[span[0]:span[1]]
    if re.search(r'\b_Generic\s*\(', body) or '#' in body:
        return []
    out = []
    for decl in DECL.finditer(body):
        var = decl['name']
        word = r'\b' + re.escape(var) + r'\b'
        # No shadowing, address escape, type-sensitive expression, or second write.
        if (len(re.findall(r'\b(?:s8|u8|s16|u16|s32|u32|int|char|short|long)\s+' + word, body)) != 1
                or re.search(r'&\s*\(*\s*' + word + r'|\b(?:sizeof|typeof|__typeof__)\s*\(*\s*' + word, body)
                or re.search(r'(?:\+\+|--)\s*' + word + '|' + word + r'\s*(?:\+\+|--|(?:<<|>>|[+*/%&|^<>-])=)', body)):
            continue
        assignments = list(re.finditer(word + r'\s*=(?!=)\s*(' + IDENT + r'\s*\([^;{}]*\))\s*;', body))
        if len(assignments) != 1 or len(re.findall(word + r'\s*=(?!=)', body)) != 1:
            continue
        assign = assignments[0]
        if len(re.findall(word, body)) < 3:
            continue
        start, end = span[0] + assign.start(1), span[0] + assign.end(1)
        kind_start, kind_end = span[0] + decl.start('kind'), span[0] + decl.end('kind')
        text = source[:start] + '(' + decl['kind'] + ') ' + source[start:end] + source[end:]
        text = text[:kind_start] + ('s32' if decl['kind'].startswith('s') else 'u32') + text[kind_end:]
        out.append((FAMILY, text))
    return out


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
