"""Fold stable copies of an opaque local pointer back into their shared source.

An SDK audio caller had three locals carrying the same voice pointer. Two copies
forced an extra spill and an eight-byte stack-frame increase under KMC GCC 2.7.
Combining the copies removed both extra instructions and took a 229-point
near-match to zero. Only unescaped, non-volatile `void *` locals qualify; the
source is not reassigned after the copies, and each copy must dominate its uses.
"""
import re

from .arm_block_support import brace_pairs
from .integer_repair_support import IDENT, edit, view

FAMILY = 'opaque_pointer_copy_fold'
LIMIT = 4
DECL = re.compile(rf'(?m)^[ \t]*void\s*\*\s*(?P<name>{IDENT})\s*;[ \t]*\n')


def _mentions(text, name, start, end):
    return list(re.finditer(rf'(?<![\w.>]){re.escape(name)}\b', text[start:end]))


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    braces = brace_pairs(clean, part.opening, part.end)
    if braces is None:
        return []
    if re.search(rf'\b(?!(?:if|for|while|switch)\b){IDENT}\s*\([^;{{}}]*\)\s*\{{',
                 clean[part.opening + 1:part.end]):
        return []  # a nested function can mutate an outer local after its textual definition
    declarations = list(DECL.finditer(clean, part.opening + 1, part.end))
    counts = {d['name']: sum(other['name'] == d['name'] for other in declarations) for d in declarations}
    decls = {d['name']: d for d in declarations if counts[d['name']] == 1
             and not any(part.opening < opening < d.start() < closing for opening, closing in braces.items())}
    macros = '\n'.join(re.findall(r'(?m)^\s*#.*(?:\\\n.*)*', source + '\n' + header))
    groups = []
    for alias, declaration in decls.items():
        hits = _mentions(clean, alias, declaration.end(), part.end)
        if len(hits) < 2:
            continue
        first = declaration.end() + hits[0].start()
        copy = re.match(rf'{re.escape(alias)}\s*=\s*(?P<origin>{IDENT})\s*;', clean[first:])
        if not copy:
            continue
        origin = copy['origin']
        if origin == alias or origin not in decls:
            continue
        # A nested declaration of either spelling can shadow the local even if
        # its type differs from `void *`.  Leave such functions to a C parser.
        shadow = rf'\b(?:const\s+|volatile\s+|struct\s+)*{IDENT}\s*(?:\*\s*|\s+)(?P<name>{re.escape(alias)}|{re.escape(origin)})\s*(?:[;=,\[])'
        if any(part.opening + 1 + m.start('name') not in (declaration.start('name'), decls[origin].start('name'))
               for m in re.finditer(shadow, clean[part.opening + 1:part.end])):
            continue
        if re.search(rf'\b(?:{re.escape(alias)}|{re.escape(origin)})\b', macros):
            continue
        start, end = first, first + copy.end()
        # Remove a whole one-shot wrapper only when it contains this copy alone.
        wrapper = re.search(r'\bdo\s*\{\s*$', clean[part.opening + 1:start])
        if wrapper:
            tail = re.match(r'\s*}\s*while\s*\(\s*0\s*\)\s*;', clean[end:])
            if tail:
                start = part.opening + 1 + wrapper.start()
                end += tail.end()
        before = clean[part.opening + 1:start].rstrip()
        if before and before[-1] not in ';{}':
            continue  # an unbraced if/loop can skip the copy
        uses = [(declaration.end() + hit.start(), declaration.end() + hit.end()) for hit in hits[1:]]
        if not uses or uses[0][0] < end:
            continue
        last = uses[-1][1]
        # Every use must stay in the lexical scopes that contain the copy.
        if any(opening < start < closing < last for opening, closing in braces.items()):
            continue
        between = clean[end:last]
        if re.search(rf'\b(?:goto|case|default|asm|__asm__|volatile)\b|(?<![\w?:]){IDENT}\s*:(?!:)', between):
            continue
        if re.search(rf'&\s*\b(?:{re.escape(alias)}|{re.escape(origin)})\b', clean[part.opening:part.end]):
            continue
        if re.search(rf'(?<![\w.>]){re.escape(origin)}\s*(?:\+\+|--|(?:<<|>>|[+\-*/%&|^])?=(?!=))|'
                     rf'(?:\+\+|--)\s*\b{re.escape(origin)}\b', clean[end:part.end]):
            continue
        if any(re.match(r'\s*(?:\+\+|--|(?:<<|>>|[+\-*/%&|^])?=(?!=))', clean[b:])
               or re.search(r'(?:\+\+|--)\s*$', clean[part.opening:a]) for a, b in uses):
            continue
        groups.append((alias, origin, [(declaration.start(), declaration.end(), ''), (start, end, '')]
                       + [(a, b, origin) for a, b in uses]))
        if len(groups) >= LIMIT:
            break
    if not groups:
        return []
    # Removing all independent aliases in one child lets the judge see the
    # combined spill effect; retain individual children for other functions.
    aliases = {alias for alias, _, _ in groups}
    edits = [change for _, _, group in groups for change in group]
    independent = all(origin not in aliases for _, origin, _ in groups)
    children = [edit(source, edits)] if len(groups) > 1 and independent else []
    children += [edit(source, group) for _, _, group in groups]
    return [(FAMILY, child) for child in dict.fromkeys(children)]


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}
