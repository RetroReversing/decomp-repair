"""Inline a float literal held in a dead local solely for the next call.

In a KMC GCC 2.7.2 O1 function, passing a literal directly instead of through a reused local changed call-register
allocation and improved the diagnostic score 195 -> 60; later steps matched exactly. Liveness includes every branch,
loop and goto: if the assigned local can be read after the call, the assignment is not removed.
"""
import re

from .csource import find
from .integer_repair_support import IDENT, edit, view
from .local_flow import Flow

FAMILY = 'float_literal_call_inline'
FAMILIES = (FAMILY,)
_DECL = re.compile(rf'(?m)^[ \t]*f32\s+(?P<name>{IDENT})\s*;[ \t]*\n')
_PAIR = re.compile(rf'(?m)^(?P<pad>[ \t]*)(?P<local>{IDENT})\s*=\s*(?P<literal>[-+]?\d+\.\d*[fF])\s*;[ \t]*\n'
                   rf'[ \t]*(?P<call>{IDENT}\s*\([^;\n]*\)\s*;)')


def variants(source, name, header=''):
    part, span = view(source, name), find(source, name)
    macros = source + '\n' + (header or '')
    if not part or not span or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean[span[0]:part.end]):
        return []
    if re.search(r'\btypedef\b[^;]*\bvolatile\b[^;]*\bf32\s*;|(?m:^\s*#\s*(?:define|undef)\s+f32\b)', macros):
        return []
    decls = list(_DECL.finditer(part.clean, part.opening + 1, part.end))
    try:
        flow = Flow(part, decls)
    except ValueError:
        return []
    out = []
    for hit in _PAIR.finditer(part.clean, part.opening + 1, part.end):
        local = hit['local']
        if (local not in flow.names or sum(decl['name'] == local for decl in decls) != 1
                or len(re.findall(r'\b[A-Za-z_]\w*(?:\s+[A-Za-z_]\w*)?\s+\**\s*'
                                  + re.escape(local) + r'\s*(?=[;=,\[])', part.clean[span[0]:part.end])) != 1
                or re.search(r'(?:\.|->)\s*' + re.escape(local) + r'\b', part.clean[span[0]:part.end])
                or len(re.findall(r'\b' + re.escape(local) + r'\b', hit['call'])) != 1
                or re.search(r'(?m)^\s*#\s*(?:define|undef)\s+[^\n]*\b' + re.escape(local) + r'\b', macros)
                or re.search(r'/[*/]|#', source[hit.start():hit.end()])):
            continue
        node = flow.at(hit.start('call'))
        if node is None or any(local in flow.nodes[i].live for i in node.successors):
            continue
        call = source[hit.start('call'):hit.end('call')]
        call = re.sub(r'\b' + re.escape(local) + r'\b', hit['literal'], call)
        out.append((FAMILY, edit(source, [(hit.start(), hit.end(), hit['pad'] + call)])))
    return out[:8]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}
