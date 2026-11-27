"""Try loop-depth weighting of a constant array store reached through a label.

A KMC MIPS -O1 state machine improved from 1370 to 1195 by enclosing the
store immediately after a label in two one-shot scopes. GCC's flow pass counts
references by loop depth; this is allocation scaffolding, not evidence of the
original source. The label remains outside, so incoming gotos still execute the
store. Each child needs judging and the scaffolding must be disclosed.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view

FAMILY = 'labeled_store_scope'
LIMIT = 12


def variants(source, name, header=''):
    part = view(source, name)
    context = source + '\n' + header
    if not part or re.search(r'\b__(?:LINE|COUNTER)__\b', context):
        return []
    macros = set(re.findall(r'(?m)^\s*#\s*(?:define|undef)\s+(' + IDENT + r')\b', context))
    pattern = rf'(?<![\w:])({IDENT})\s*:(?!:)\s*({IDENT})\s*\[\s*({IDENT}|{NUMBER})\s*\]\s*=\s*({NUMBER})\s*;'
    out = []
    for hit in re.finditer(pattern, part.body):
        if hit[1] in {'case', 'default'} or set(hit.group(i) for i in (1, 2, 3)) & macros:
            continue
        start = part.opening + 1 + hit.start(2)
        end = part.opening + 1 + hit.end()
        statement = source[start:end]
        for depth in (1, 2, 4):
            wrapped = 'do { ' * depth + statement + ' } while (0);' * depth
            out.append((FAMILY, edit(source, [(start, end, wrapped)])))
            if len(out) >= LIMIT:
                return out
    return out


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}
