"""Reuse a dead float local as a constant carrier before its next assignment.

In one KMC -O1 function this produces the target's two saved float registers;
the precise GCC allocation cause is a hypothesis. The literal and arithmetic
are unchanged, and the carrier is overwritten before its next use.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'float_constant_local_reuse'


def variants(source, name, flags=(), header=""):
    context = source + '\n' + (header or '')
    if re.search(r'(?m)^\s*#\s*(?:define|undef)\s+(?:f32|float)\b|\btypedef\b[^;]*\bvolatile\b[^;]*\bf32\s*;', context):
        return []
    part = view(source, name)
    if not part or '-O1' not in flags:
        return []
    body = part.clean[part.opening:part.end]
    if re.search(r'\b(?:volatile|goto|asm|__asm__)\b', body):
        return []
    decls = re.findall(r'(?m)^\s*(?:f32|float)\s+(' + IDENT + r'(?:\s*,\s*' + IDENT + r')*)\s*;', body)
    names = [name for decl in decls for name in re.findall(IDENT, decl)]
    pattern = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<dest>' + IDENT + r')\s*(?P<op>[+-]=)\s*(?P<literal>(?:\d+\.\d*|\.\d+)[fF])\s*;')
    result = []
    for match in pattern.finditer(body):
        for carrier in names:
            if (carrier == match['dest'] or re.search(r'&\s*' + re.escape(carrier) + r'\b', body)
                    or len(re.findall(r'\b' + re.escape(carrier) + r'\b', body[:match.start()])) != 1):
                continue
            # The old value is dead: the next reference must overwrite it.
            later = re.search(r'\b' + re.escape(carrier) + r'\b', body[match.end():])
            if not later:
                continue
            tail = body[match.end() + later.start():]
            assignment = re.match(re.escape(carrier) + r'\s*=(?!=)([^;]*);', tail)
            if not assignment or re.search(r'\b' + re.escape(carrier) + r'\b', assignment[1]):
                continue
            statement = (f'{match["indent"]}{carrier} = {match["literal"]}; '
                         f'{match["dest"]} {match["op"]} {carrier};')
            result.append((FAMILY, edit(source, [(part.opening + match.start(),
                                                  part.opening + match.end(), statement)])))
    return result


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'flags', 'header'), 'archs': ('mips',), 'order': 42}
