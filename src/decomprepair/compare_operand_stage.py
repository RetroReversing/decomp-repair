"""Stage the right operand of a float comparison in a local: `if (d1 < (a - b))` -> `d2 = a - b; if (d1 < d2)`.

GCC 2.x numbers pseudo registers in expansion order and local-alloc gives the caller-saved registers out in that
order, so when two operands of one subtraction are loaded the first expanded one takes the lower register. In
`d1 < (sum.y - out.y)` the subtraction's operands are expanded inside the comparison, after d1's own operands; a
named local for the difference is a user variable, expanded as its own statement, and gets its pseudo (and so its
register) at a different point: a function whose two such comparisons had `$f0`/`$f2` exchanged in the second
subtraction went 282 -> 250 with `d2 = sum.y - out.y; if (d1 < d2)`.

The right operand must be a parenthesised binary arithmetic expression of plain operands (identifiers, members,
constants), compared with a declared float local; an identity inline helper wrapped around an operand (the author of a
draft used one to push an operand to the front) is removed on the way. One site at a time, then every site of that
shape together. Needs one new local: it is declared at the head of the function."""
import re

from .integer_repair_support import IDENT, edit, view

FAMILIES = ('compare_operand_stage',)
LIMIT = 12
OPERAND = rf'(?:{IDENT}(?:\s*(?:\.|->)\s*{IDENT})*|[0-9.]+f?)'
TEST = re.compile(rf'\bif\s*\(\s*(?P<left>{IDENT})\s*(?P<cmp><=|>=|<|>)\s*\(\s*(?P<a>{OPERAND})\s*(?P<op>[-+*])\s*(?P<b>{OPERAND}|{IDENT}\s*\(\s*{OPERAND}\s*\))\s*\)\s*\)')
FLOATS = r'(?:f32|float|f64|double)'


def identities(source):
    """Names of helpers that return their float argument unchanged (a draft's way to reorder an operand)."""
    helper = rf'(?:(?:inline|static)\s+)+(?:{FLOATS})\s+({IDENT})\s*\(\s*(?:{FLOATS})\s+({IDENT})\s*\)\s*{{\s*return\s+\2\s*;\s*}}'
    return {m[0] for m in re.findall(helper, source)}


def variants(source, name, header=''):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.body) or '__stage_cmp' in source:
        return []
    kinds = {n: t for t, n in re.findall(rf'\b({FLOATS})\s+({IDENT})\s*;', part.clean[part.opening:part.end])}
    helpers = identities(source)
    sites = []
    for hit in TEST.finditer(part.clean, part.opening, part.end):
        if hit['left'] not in kinds:
            continue
        right = hit['b']
        call = re.fullmatch(rf'({IDENT})\s*\(\s*({OPERAND})\s*\)', right)
        if call:
            if call[1] not in helpers:
                continue
            right = call[2]
        sites.append((hit, kinds[hit['left']], f"{hit['a']} {hit['op']} {right}"))
    if not sites:
        return []
    names = {}

    def declare(kind):
        return names.setdefault(kind, f'__stage_cmp_{kind}')

    def build(chosen):
        edits, kinds_used = [], []
        for number, (hit, kind, expression) in enumerate(chosen):
            local = f'{declare(kind)}'
            if kind not in kinds_used:
                kinds_used.append(kind)
            line = source.rfind('\n', 0, hit.start()) + 1
            indent = source[line:hit.start()] if not source[line:hit.start()].strip() else ''
            edits.append((hit.start(), hit.end(), f"{local} = {expression};\n{indent}if ({hit['left']} {hit['cmp']} {local})"))
        opening = part.opening + 1
        edits.append((opening, opening, ''.join(f'\n  {kind} {names[kind]};' for kind in kinds_used)))
        return edit(source, edits)

    out = [(FAMILIES[0], build([site])) for site in sites[:LIMIT]]
    if len(sites) > 1:
        out.append((FAMILIES[0], build(sites[:LIMIT])))
    return list(dict.fromkeys(out))
