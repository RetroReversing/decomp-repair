"""Move byte or halfword narrowing to the use sites indicated by KMC's instruction order."""

import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, view

FAMILY = 'measured_narrow_use'
REG = r'\$\w+'
MASK8 = re.compile(rf'andi {REG}, ({REG}), (?:0xff|255)')
MASK16 = re.compile(r'andi \$v0, \$v0, (?:0xffff|65535)')
SIGNED = r'(?:s32|int)'
WORD = rf'(?:{SIGNED}|u32|unsigned\s+int)'
INLINE = re.compile(rf'\b(?:inline\s+static|static\s+inline)\s+u8\s+({IDENT})\s*\(')


def _byte_uses(source, part, rows):
    target_registers = [m[1] for _, target, _ in rows if (m := MASK8.fullmatch(target))]
    if (len(target_registers) == len(set(target_registers))
            or not any(not candidate and MASK8.fullmatch(target) for _, target, candidate in rows)):
        return []
    for definition in INLINE.finditer(part.clean, 0, part.opening):
        helper_name = definition[1]
        if not re.search(rf'\b{helper_name}\s*\(', part.body):
            continue
        helper = view(source, helper_name)
        args = re.match(rf'\s*[^()]*?,\s*{WORD}\s+({IDENT})\s*\)', part.clean[definition.end():part.opening])
        if not helper or not args:
            continue
        parameter = args[1]
        assigned = re.search(rf'(?<=[;{{}}])\s*(?P<name>{IDENT})\s*=\s*(?P<cast>\(\s*u8\s*\)\s*){parameter}\s*;',
                             helper.clean[helper.opening:helper.end])
        if not assigned:
            continue
        name = assigned['name']
        if not re.search(rf'(?<=[;{{}}])\s*{WORD}\s+{name}\s*;', helper.clean[helper.opening:helper.opening + assigned.start()]):
            continue
        indexed = re.search(rf'\b{IDENT}\s*\[\s*(?P<use>{name})\s*\]', helper.body)
        compared = re.search(rf'\bif\s*\(\s*{IDENT}\s*==\s*(?P<use>{name})\s*\)', helper.body)
        if (not indexed or not compared or len(re.findall(rf'\b{name}\b', helper.body)) != 4
                or min(indexed.start(), compared.start()) < assigned.end() - 1):
            continue
        offset = helper.opening + 1
        edits = [(helper.opening + assigned.start('cast'), helper.opening + assigned.end('cast'), '')]
        edits += [(offset + m.start('use'), offset + m.end('use'), f'(u8){name}') for m in (indexed, compared)]
        return [(FAMILY, edit(source, edits))]
    return []


def _remainder(source, part, rows):
    target, candidate = ([op for row in rows if (op := row[index])] for index in (1, 2))
    if not (any(MASK8.fullmatch(a) and MASK16.fullmatch(b) for a, b in zip(target, target[1:]))
            and any(MASK16.fullmatch(a) and MASK8.fullmatch(b) for a, b in zip(candidate, candidate[1:]))):
        return []
    pattern = re.compile(
        rf'(?<=[;{{}}])\s*(?P<var>{IDENT})\s*=\s*{IDENT}\s*\(\s*\)(?P<mask>\s*&\s*(?:0[xX][fF]{{4}}|65535))\s*;'
        rf'\s*(?P=var)\s*=\s*(?P<use>(?P=var))\s*%'
    )
    for hit in pattern.finditer(part.clean, part.opening, part.end):
        var = hit['var']
        if (not re.search(rf'(?<=[;{{}}])\s*{SIGNED}\s+{var}\s*;', part.clean[part.opening:hit.start()])
                or re.search(rf'&\s*\(*\s*{var}\b', part.body)):
            continue
        return [(FAMILY, edit(source, [(*hit.span('mask'), ''), (*hit.span('use'), f'(u16){var}')]))]
    return []


def variants(source, name, rows):
    """Offer both repairs separately so the next diff can guide the other one."""
    if not any('andi ' in row[1] for row in rows):
        return []
    part = view(source, name)
    if not part or re.search(r'\b(?:goto|asm|__asm__)\b', _blank(source)):
        return []
    return _byte_uses(source, part, rows) + _remainder(source, part, rows)
