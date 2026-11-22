"""Try short-circuit spelling for two proven boolean locals in a guard."""

import re

from .csource import _blank
from .frame_padding_repairs import declaration_ends
from .integer_repair_support import IDENT, edit, locals_for, refs, view
from .pointer_pair_repairs import qualified_types

FAMILY = 'boolean_guard_operands'
_GUARD = re.compile(rf'&&\s*\(\s*({IDENT})\s*(&)(?!&)\s*\(\s*({IDENT})\s*!=\s*NULL\s*\)\s*\)')
_NONZERO = re.compile(r'sltu (\$\w+), \$zero, (\$\w+)')


def _witness(rows):
    for index, (_, target, candidate) in enumerate(rows[:-1]):
        comparison = _NONZERO.fullmatch(target)
        if not comparison or not candidate.startswith(f'beqz {comparison[2]}, '):
            continue
        _, left, right = rows[index + 1]
        if (left.startswith('and ') and comparison[1] in left.split(', ')[1:]
                and right.startswith('andi ') and right.endswith(', 1')):
            return True
    return False


def variants(source, name, rows, header=''):
    if not _witness(rows):
        return []
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm|__asm__)\b', part.body):
        return []
    context = _blank(header) + '\n' + part.clean
    scalars = {d['name']: d for d in locals_for(part) if d['type'] not in qualified_types(context)}
    pointers = set()
    begin = part.opening + 1
    for end in declaration_ends(part):
        declaration = re.fullmatch(rf'\s*void\s*\*\s*({IDENT})\s*;', part.clean[begin:end])
        if declaration:
            pointers.add(declaration[1])
        begin = end
    macros = re.findall(r'(?m)^[ \t]*#\s*(?:define|undef)\s+([^\n]+)', context)
    out = []
    for hit in _GUARD.finditer(part.clean, part.opening + 1, part.end):
        flag, operator, ptr = hit.groups()
        if flag not in scalars or ptr not in pointers:
            continue
        names = (flag, ptr)
        if any(len(re.findall(rf'\b{IDENT}(?:\s+\**\s*|\s*\*+\s*){re.escape(var)}\s*(?=[;=,\[])',
                              part.body)) != 1 for var in names):
            continue
        if any(set(re.findall(IDENT, macro)) & {flag, ptr} for macro in macros):
            continue
        if any(macro.startswith('NULL') and not re.fullmatch(
                r'NULL\s+(?:0|\(0\)|\(\s*\(\s*void\s*\*\s*\)\s*0\s*\))\s*', macro)
                for macro in macros):
            continue
        others = [ref for ref in refs(part, scalars[flag]) if ref.start() != hit.start(1)]
        if not others or any(not re.match(
                rf'\s*=\s*({IDENT})\s*(?:!=|==)\s*NULL\s*[,;)]', part.clean[ref.end():])
                for ref in others):
            continue
        if any(re.search(r'(?:\+\+|--|(?<!&)\&(?!&))\s*\(*\s*$', part.clean[:ref.start()])
               for ref in others):
            continue
        if source[hit.start(2):hit.end(2)] == operator:
            out.append((FAMILY, edit(source, [(hit.start(2), hit.end(2), '&&')])))
    return out[:4]
