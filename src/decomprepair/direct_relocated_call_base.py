"""Use the relocated symbol directly when a byte-pointer copy changes call registers."""

import re

from .csource import _blank
from .integer_repair_support import IDENT, INTEGER, calls, edit, split_args, view

FAMILY = 'direct_relocated_call_base'
_TARGET = re.compile(
    rf'lui (?P<argument>\$a[0-3]), %hi\((?P<symbol>{IDENT})\)\n'
    r'addiu (?P=argument), (?P=argument), %lo\((?P=symbol)\)\n'
    rf'(?:[^\n]+\n){{0,8}}?jal (?P<callee>{IDENT})\n'
    r'addu (?P=argument), (?P<offset>\$v[01]), (?P=argument)(?:\n|$)'
)


def variants(source, name, header, rows):
    rows = list(rows)
    target = '\n'.join(left for _, left, _ in rows if left)
    candidate = '\n'.join(right for _, _, right in rows if right)
    part = view(source, name)
    if not part:
        return []
    declarations = _blank(header) + '\n' + part.clean
    macros = set(re.findall(rf'(?m)^\s*#\s*define\s+({IDENT})', declarations))
    results = []
    for witness in _TARGET.finditer(target):
        arg, symbol, callee, offset = (witness[key] for key in ('argument', 'symbol', 'callee', 'offset'))
        if not re.search(
                rf'lui (\$t[0-9]), %hi\({symbol}\)\naddiu \1, \1, %lo\({symbol}\)\n'
                rf'(?:[^\n]+\n){{0,8}}?jal {callee}\naddu {re.escape(arg)}, \1, {re.escape(offset)}(?:\n|$)',
                candidate):
            continue
        if not re.search(rf'\bextern\s+char\s+{symbol}\s*\[\s*\w*\s*\]\s*;', declarations):
            continue
        sites = list(calls(part, callee))
        if len(sites) != 1:
            continue
        start, end = sites[0]
        spans = split_args(part.clean[start:end])
        slot = int(arg[-1])
        if len(spans) <= slot:
            continue
        begin, end = (start + pos for pos in spans[slot])
        original = source[begin:end]
        hit = re.fullmatch(rf'(\s*\(s32\)\s*\()(?P<base>{IDENT})\s*\+\s*(?P<index>{IDENT})(\)\s*)',
                           original)
        if not hit:
            continue
        base, index = hit['base'], hit['index']
        if {base, index, symbol, callee, 's32'} & macros:
            continue
        bindings = list(re.finditer(rf'\bchar\s*\*\s*{base}\s*=\s*{symbol}\s*;', part.clean, re.M))
        if len(bindings) != 1 or len(re.findall(rf'\b{base}\b', part.body)) != 2:
            continue
        if len(re.findall(rf'\b{symbol}\b', part.body)) != 1:
            continue
        if not re.search(rf'\b{INTEGER}\s+{index}\s*;', part.body):
            continue
        declaration = bindings[0]
        if not part.opening < declaration.start() < begin:
            continue
        replacement = f'{hit[1]}{index} + {symbol}{hit[4]}'
        results.append((FAMILY, edit(source, [(begin, end, replacement)])))
    return list(dict.fromkeys(results))
