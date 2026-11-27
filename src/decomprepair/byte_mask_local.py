"""Narrow a word local whose only assigned value is masked to one byte.

A MIPS handler kept a channel number in an s32 even though its sole definition
masked it with 255. Declaring that local u8 kept the same integer value and
changed one KMC GCC 2.7.2 score from 3175 to 2825. The allocation explanation
is a hypothesis, not a compiler-source finding. Address-taking, sizeof, shadows,
other assignments, and volatile or macro-defined byte types are rejected.
"""
import re

from .case_temporary_repairs import DECLARATION, _depth_at
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'byte_mask_local'
FAMILIES = (FAMILY,)


def variants(source, name, header=''):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or re.search(r'\bvolatile\b', clean[opening:end]):
        return []
    context = source + '\n' + (header or '')
    if re.search(r'(?m)^\s*#\s*(?:define|undef)\s+u8\b|\btypedef\b[^;]*\bvolatile\b[^;]*\bu8\s*;', context):
        return []
    declarations = list(DECLARATION.finditer(clean, opening + 1, end))
    out = []
    for decl in declarations:
        var = decl['name']
        if decl['type'].strip() not in ('s32', 'int') or _depth_at(clean, opening + 1, decl.start()):
            continue
        if sum(d['name'] == var for d in declarations) != 1:
            continue
        if re.search(r'(?m)^\s*#\s*(?:define|undef)\s+' + re.escape(var) + r'\b', context):
            continue
        body = clean[decl.end():end]
        if re.search(r'(?:&\s*|\+\+\s*|--\s*|\bsizeof\s*\(?\s*)' + re.escape(var) + r'\b', body):
            continue
        writes = list(re.finditer(r'\b' + re.escape(var) + r'\s*(?:\+\+|--|[+*/%&|^\-]?=(?!=))', body))
        if len(writes) != 1:
            continue
        assignment = re.match(r'\b' + re.escape(var) + r'\s*=\s*\(?\s*[A-Za-z_]\w*\s*&\s*(?:0[xX][fF]{2}|255)[uU]?\s*\)?\s*;', body[writes[0].start():])
        if not assignment:
            continue
        # Keep integer promotions immaterial: the remaining reads only compare
        # the byte for equality or multiply it by a bounded integer literal.
        rhs_end = writes[0].start() + assignment.end()
        if any(not (re.search(r'==\s*$', body[:rhs_end + use.start()]) or
                    ((scale := re.match(r'\s*\*\s*(0[xX][0-9a-fA-F]+|\d+)\b', body[rhs_end + use.end():]))
                     and int(scale[1], 0) <= 0x7fffff))
               for use in re.finditer(r'\b' + re.escape(var) + r'\b', body[rhs_end:])):
            continue
        # Declarations from other types and pointer aliases are also shadows.
        if len(re.findall(r'(?m)(?:^|[;{}])[ \t]*[A-Za-z_][\w \t*]*[ \t*]' + re.escape(var) + r'\s*[;=]', clean[opening:end])) != 1:
            continue
        type_start = decl.start('type')
        type_end = type_start + len(decl['type'].rstrip())
        out.append((FAMILY, source[:type_start] + 'u8' + source[type_end:]))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 40}
