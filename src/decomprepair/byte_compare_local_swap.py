"""Swap an indexed byte read and a plain local across a relational operator.

In a KMC O1 state handler, writing `byte < local` as `local > byte` improved
one linked diagnostic from 3530 to 3480. Both operands are side-effect-free;
the exact judge decides whether the spelling helps.
"""
import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, view

FAMILY = 'byte_compare_local_swap'
LIMIT = 8
FLIP = {'<': '>', '>': '<', '<=': '>=', '>=': '<='}


def variants(source, name, header='', flags=None):
    if any(f.startswith(('-D', '-include', '-imacros', '-Wp,', '-Xpreprocessor', '@')) for f in flags or ()):
        return []
    context = source + '\n' + header
    if re.search(r'(?m)^\s*#\s*(?:include(?:_next)?|import)\b|\bvolatile\b', context):
        return []
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    body = clean[part.opening + 1:part.end]
    if (re.search(r'(?m)^\s*#\s*(?:if|ifdef|ifndef|elif|else|endif)\b', body)
            or re.search(r'\b(?:asm|__asm__|_Atomic)\b', body)):
        return []
    directives = '\n'.join(re.findall(r'(?m)^\s*#.*(?:\\\n.*)*', context))
    macros = set(re.findall(rf'(?m)^\s*#\s*define\s+({IDENT})\b', directives))
    if macros.intersection(re.findall(IDENT, body)) or {'if', 'u8', name} & macros:
        return []
    pattern = (rf'\bif\s*\(\s*(?P<read>\(\s*u8\s*\)\s*\*\s*\(\s*{IDENT}\s*\+\s*{IDENT}\s*\))'
               rf'\s*(?P<op><=|>=|<|>)\s*(?P<local>{IDENT})\s*\)')
    result = []
    for match in re.compile(pattern).finditer(clean, part.opening + 1, part.end):
        local = match['local']
        # A real scalar local keeps the rewrite away from function-like names and exotic declarations.
        if not re.search(rf'(?m)^[ \t]*u8\s+{re.escape(local)}\s*;', _blank(body)):
            continue
        expression = f"{local} {FLIP[match['op']]} {source[match.start('read'):match.end('read')]}"
        result.append((FAMILY, edit(source, [(match.start('read'), match.end('local'), expression)])))
        if len(result) >= LIMIT:
            return result
    return result


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header', 'flags'),
          'archs': ('mips',)}
