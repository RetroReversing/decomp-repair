"""Reuse ordinary float locals whose values are disjoint in the full control-flow graph.

On one KMC GCC 2.7.2 function, two non-overlapping float values shared a local and improved O2 45,965 -> 45,685;
another pair improved the O1 diagnostic 505 -> 195. Later steps matched the function exactly. Unlike textual
lifetime guesses, liveness includes branches, switches, loops and goto edges; simultaneous live values or a write
while the other value is live prevent a merge. The judge decides which safe reuse matches the target allocation.
"""
import itertools
import re

from .csource import find
from .integer_repair_support import IDENT, edit, view
from .local_flow import Flow

FAMILY = 'float_cfg_local_reuse'
FAMILIES = (FAMILY,)
LIMIT = 128
_DECL = re.compile(rf'(?m)^[ \t]*f32\s+(?P<name>{IDENT})\s*;[ \t]*\n')


def variants(source, name, header=''):
    part, span = view(source, name), find(source, name)
    macros = source + '\n' + (header or '')
    if not part or not span or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean[span[0]:part.end]):
        return []
    if re.search(r'\btypedef\b[^;]*\bvolatile\b[^;]*\bf32\s*;|(?m:^\s*#\s*(?:define|undef)\s+f32\b)', macros):
        return []
    decls = []
    for decl in _DECL.finditer(part.clean, part.opening + 1, part.end):
        local = decl['name']
        prefix = part.clean[part.opening + 1:decl.start()]
        if (prefix.count('{') != prefix.count('}')
                or len(re.findall(r'\b[A-Za-z_]\w*(?:\s+[A-Za-z_]\w*)?\s+\**\s*'
                                  + re.escape(local) + r'\s*(?=[;=,\[])', part.clean[span[0]:part.end])) != 1
                or re.search(r'(?:\.|->)\s*' + re.escape(local) + r'\b', part.clean[span[0]:part.end])
                or re.search(r'(?m)^\s*#\s*(?:define|undef)\s+[^\n]*\b' + re.escape(local) + r'\b', macros)):
            continue
        decls.append(decl)
    if len(decls) < 2 or len(decls) > 128:
        return []
    try:
        flow = Flow(part, decls)
    except ValueError:
        return []
    refs = {}
    for decl in decls:
        local = decl['name']
        if local not in flow.names:
            continue
        hits = [m for m in re.finditer(r'(?<![\w.>])' + re.escape(local) + r'\b', part.clean[decl.end():part.end])]
        if hits:
            refs[local] = [(decl.end() + m.start(), decl.end() + m.end()) for m in hits]
    conflicts = set()
    definitions = {}
    for node in flow.nodes:
        if any(decl.start() <= node.start < decl.end() for decl in decls):
            continue  # declaration names are not reads
        outgoing = set().union(*(flow.nodes[i].live for i in node.successors))
        conflicts.update(frozenset(pair) for pair in itertools.combinations(node.live, 2))
        conflicts.update(frozenset((a, b)) for a in node.defines for b in outgoing if a != b)
        for local in node.defines:
            definitions[local] = definitions.get(local, 0) + 1
    candidates = []
    for early in decls:
        a = early['name']
        if a not in refs:
            continue
        for donor in decls:
            b = donor['name']
            if a == b or b not in refs or refs[a][-1][1] >= refs[b][0][0]:
                continue
            if frozenset((a, b)) in conflicts:
                continue
            defs = definitions.get(b, 0)
            # Saved argument temporaries and locals assigned on several arms often explain register ties.
            rank = (not bool(re.fullmatch(r'sp[0-9A-Fa-f]+', b)), defs < 2, refs[b][0][0] - refs[a][-1][1], a, b)
            candidates.append((rank, early, a, b))
    out = []
    for _, decl, a, b in sorted(candidates, key=lambda item: item[0])[:LIMIT]:
        changes = [(decl.start(), decl.end(), '')]
        changes += [(start, end, b) for start, end in refs[a]]
        out.append((FAMILY, edit(source, changes)))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}
