"""Reuse a case-local word temporary for an earlier switch selector.

A MIPS handler computes a masked command in a scratch word, then uses a
separate word for a selector inside one case. Reusing the second word for the
initial switch changed a KMC GCC 2.7.2 isolated score from 350 to 295. Every
case that reads the second word must first assign it; its earlier selector
value is therefore dead, and no value flows out of the switch through it.
"""
import re

from . import local_flow, pointer_pair_repairs
from .case_temporary_repairs import DECLARATION, _depth_at, _eligible, _groups, _switches
from .csource import _blank, find
from .integer_repair_support import IDENT, edit
from .pattern_repairs import close

FAMILY = 'switch_selector_phase_reuse'
FAMILIES = (FAMILY,)


def variants(source, name, header=''):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or re.search(r'\b(?:volatile|goto|asm|__asm__)\b', clean[opening:end]):
        return []
    context = source + '\n' + (header or '')
    if re.search(r'(?m)^\s*#\s*(?:define|undef)\s+s32\b|\btypedef\b[^;]*\bvolatile\b[^;]*\bs32\s*;', context):
        return []
    declarations = [d for d in DECLARATION.finditer(clean, opening + 1, end)
                    if d['type'].strip() == 's32' and not _depth_at(clean, opening + 1, d.start())]
    switches = _switches(clean, opening, end)
    result = []
    if not pointer_pair_repairs.context(source, name, header)[0]:
        return []
    flow = local_flow.analyze(source, name)
    if not flow:
        return []
    pattern = re.compile(r'(?m)^[ \t]*(?P<old>' + IDENT + r')\s*=\s*' + IDENT + r'\s*&\s*(?:0[xX][fF]0|240)\s*;\s*switch\s*\(\s*(?P=old)\s*\)\s*\{')
    for match in pattern.finditer(clean, opening + 1, end):
        body = next((item for item in switches if item[0] == match.end() - 1), None)
        if not body:
            continue
        selector_at = clean.rfind(match['old'], match.start(), match.end())
        nodes = [node for node in flow.nodes if node.start == selector_at and node.end == selector_at + len(match['old'])]
        if (len(nodes) != 1 or match['old'] not in flow.names
                or any(match['old'] in flow.nodes[i].live for i in nodes[0].successors)):
            continue
        nested = [item for item in switches if body[0] < item[0] and item[1] < body[1]]
        groups = _groups(clean, body, nested)
        if not groups:
            continue
        for decl in declarations:
            var = decl['name']
            if var not in flow.names or var == match['old'] or decl.start() > match.start():
                continue
            if sum(d['name'] == var for d in declarations) != 1:
                continue
            if re.search(r'(?m)^\s*#\s*(?:define|undef)\s+(?:' + re.escape(var) + '|' + re.escape(match['old']) + r')\b', context):
                continue
            outside = [(opening, decl.start()), (decl.end(), body[0]), (body[1], end)]
            if not _eligible(clean, var, groups, outside):
                continue
            end_old = match.start('old') + len(match['old'])
            selector = re.search(r'\bswitch\s*\(\s*(' + re.escape(match['old']) + r')\s*\)', clean[end_old:match.end()])
            if not selector:
                continue
            a = end_old + selector.start(1)
            result.append((FAMILY, edit(source, [(match.start('old'), end_old, var), (a, a + len(match['old']), var)])))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 40}
