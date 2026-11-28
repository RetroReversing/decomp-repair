"""Inline one unescaped local copied from another when neither can change before its only use.

A nested scan in one KMC MIPS O1 state machine kept an entry-index copy in
an extra register. Inlining that copy into its only comparison removed an
instruction and improved the exact judge from 655 to 550. Both locals must be
ordinary unescaped scalars of the same type; intervening writes, labels and
macro references make the candidate ineligible.
"""
import re

from .arm_block_support import brace_pairs
from .integer_repair_support import IDENT, edit, locals_for, view

FAMILY = 'single_local_copy_inline'
LIMIT = 12


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    context = source + '\n' + header
    macros = re.findall(r'(?m)^\s*#\s*define\b(?:[^\n\\]|\\\n)*', context)
    declarations = {d['name']: d for d in locals_for(part)}
    pairs = brace_pairs(part.clean, part.opening, part.end)
    if not pairs:
        return []
    result = []
    for target, decl in declarations.items():
        hits = list(re.finditer(r'\b' + re.escape(target) + r'\b', part.clean[part.opening:part.end]))
        if len(hits) != 3:
            continue
        assign = re.search(rf'\b{re.escape(target)}\s*=\s*({IDENT})\s*;', part.body)
        if not assign:
            continue
        origin = assign[1]
        if origin == target or origin not in declarations or declarations[origin]['type'] != decl['type']:
            continue
        if any(re.search(rf'\b(?:{re.escape(target)}|{re.escape(origin)})\b', macro) for macro in macros):
            continue
        start = part.opening + 1 + assign.start()
        end = part.opening + 1 + assign.end()
        use = part.opening + hits[-1].start()
        if not (decl.end() <= start < end <= use):
            continue
        before = part.clean[part.opening + 1:start].rstrip()
        if before and before[-1] not in ';{}':
            continue  # an unbraced conditional could skip the copy
        if any(opening < start < closing < use for opening, closing in pairs.items()):
            continue  # the use must remain inside every scope containing the copy
        between = part.clean[end:use]
        if (re.search(rf'\b{re.escape(origin)}\s*(?:\+\+|--|(?:<<|>>|[+\-*/%&|^])?=(?!=))|(?:\+\+|--)\s*{re.escape(origin)}\b', between)
                or re.search(rf'\b(?:goto|case|default|asm|__asm__|volatile)\b|(?<![\w?:]){IDENT}\s*:(?!:)', between)):
            continue
        after_use = part.clean[use + len(target):part.end]
        if re.search(r'(?:\+\+|--)\s*$', between) or re.match(r'\s*(?:\+\+|--|(?:<<|>>|[+\-*/%&|^])?=(?!=))', after_use):
            continue
        result.append((FAMILY, edit(source, [(decl.start(), decl.end(), ''), (start, end, ''),
                                             (use, use + len(target), origin)])))
        if len(result) >= LIMIT:
            break
    return result


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}
