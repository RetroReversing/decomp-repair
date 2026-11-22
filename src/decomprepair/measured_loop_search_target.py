"""Stage a measured invariant sum inside a nonempty linked-list search."""

import re

from .integer_repair_support import IDENT, edit, locals_for, view
from .pattern_repairs import close

REG = r'\$[a-z0-9]+'
TARGET = re.compile(
    rf'beqz (?P<node>{REG}), [^\n]+\nnop\naddu (?P<sum>{REG}), (?P<a>{REG}), (?P<b>{REG})\n'
    rf'lw (?P<tmp>{REG}), [^\n]+\((?P=node)\)\nlw (?P<value>{REG}), [^\n]+\((?P=tmp)\)\n'
    rf'beq (?P=value), (?P=sum), [^\n]+'
)
CANDIDATE = re.compile(
    rf'beqz (?P<node>{REG}), [^\n]+\nnop\nlw (?P<tmp>{REG}), [^\n]+\((?P=node)\)\n'
    rf'lw (?P<value>{REG}), [^\n]+\((?P=tmp)\)\naddu (?P<sum>{REG}), (?P<a>{REG}), (?P<b>{REG})\n'
    rf'beq (?P=value), (?P=sum), [^\n]+'
)


def variants(source, name, header, rows):
    target = '\n'.join(' '.join(left.split()) for _, left, _ in rows if left)
    candidate = '\n'.join(' '.join(right.split()) for _, _, right in rows if right)
    t, c = TARGET.search(target), CANDIDATE.search(candidate)
    if not t or not c or (t['a'], t['b']) != (c['a'], c['b']):
        return []
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean):
        return []
    scalars = {decl['name']: decl['type'] for decl in locals_for(part) if decl['type'] in ('s32', 'u32', 'int')}
    guard = re.compile(rf'if\s*\(\s*(?P<node>{IDENT})\s*!=\s*NULL\s*\)\s*{{\s*(?P<label>{IDENT})\s*:')
    result = []
    for loop in guard.finditer(part.clean, part.opening + 1, part.end):
        opening = part.clean.index('{', loop.start(), loop.end())
        end = close(part.clean, opening, '{', '}')
        if not end:
            continue
        loop_body = part.clean[loop.end():end - 1]
        if (len(re.findall(rf'\bgoto\s+{re.escape(loop["label"])}\s*;', loop_body)) != 1
                or len(re.findall(rf'\bgoto\s+{re.escape(loop["label"])}\s*;', part.body)) != 1):
            continue
        if set(re.findall(rf'\b({IDENT})\s*\(', loop_body)) - {'if', 'M2C_FIELD'}:
            continue
        # The sum consists only of unescaped local integers, never assigned in
        # the loop. It is evaluated only after the existing non-null guard.
        sums = list(re.finditer(rf'\(\s*(?P<a>{IDENT})\s*\+\s*(?P<b>{IDENT})\s*\)', loop_body))
        if len(sums) != 1:
            continue
        hit = sums[0]
        if hit['a'] not in scalars or hit['b'] not in scalars or hit['a'] == hit['b']:
            continue
        if any(re.search(rf'(?m)^\s*#\s*define\s+{re.escape(x)}\b', source + '\n' + header)
               for x in (hit['a'], hit['b'])):
            continue
        if any(re.search(rf'(?:\b{re.escape(x)}\s*(?:[+*/%&|^\-]?=|\+\+|--)|'
                         rf'(?:\+\+|--)\s*{re.escape(x)}\b)', loop_body) for x in (hit['a'], hit['b'])):
            continue
        if not re.search(rf'\bif\s*\([^;{{}}]*!=\s*\(\s*{re.escape(hit["a"])}\s*\+\s*'
                         rf'{re.escape(hit["b"])}\s*\)', loop_body):
            continue
        tmp = '__repair_search_target'
        if re.search(rf'\b{tmp}\b', source + '\n' + header):
            continue
        typ = 'u32' if 'u32' in (scalars[hit['a']], scalars[hit['b']]) else 's32'
        offset = loop.end() + hit.start()
        edits = [(part.opening + 1, part.opening + 1, f'\n    {typ} {tmp};'),
                 (loop.start('label'), loop.start('label'), f'{tmp} = {hit["a"]} + {hit["b"]};\n'),
                 (offset, offset + len(hit[0]), tmp)]
        result.append(('measured_loop_search_target', edit(source, edits)))
    return result[:1]
