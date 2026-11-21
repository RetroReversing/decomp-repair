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


HALFWORD_INDEX = 'shared_halfword_index'


def _halfword_index_callees(rows):
    """Find two halfword-index calls with a common target carrier and different candidate carriers."""
    masked = re.compile(rf'andi (?P<dst>{REG}), \$v0, 0xffff')
    calls = {}
    for call, delay, mask, scale, add, load in zip(rows, rows[1:], rows[2:], rows[3:], rows[4:], rows[5:]):
        callee = re.fullmatch(rf'jal ({IDENT})', call[1])
        target, candidate = (masked.fullmatch(op) for op in mask[1:])
        if (not callee or call[1] != call[2] or delay[1] != delay[2] or not target or not candidate
                or target['dst'] == candidate['dst'] or add[1] != add[2]):
            continue
        if (scale[1] != f'sll $v0, {target["dst"]}, 1' or scale[2] != f'sll $v0, {candidate["dst"]}, 1'
                or not all(re.fullmatch(rf'lh {REG}, \(\$v0\)', op) for op in load[1:])):
            continue
        key = callee[1], target['dst']
        calls.setdefault(key, set()).add(candidate['dst'])
    return {callee for (callee, _), carriers in calls.items() if len(carriers) >= 2}


def shared_halfword_index_variants(source, name, rows):
    """Reuse a narrowed call result across two score loops and inline the second load."""
    callees = _halfword_index_callees(rows)
    if not callees or not (part := view(source, name)) or re.search(r'\bvolatile\b', part.body):
        return []
    access = rf'{IDENT}\s*\.\s*(?P<field>{IDENT})'
    first = re.compile(
        rf'\bdo\s*{{\s*(?P<decl>u16\s+)(?P<slot>{IDENT})\s*=\s*'
        rf'(?P<callee>{IDENT})\s*\(\s*\(u16\)\s*(?P<i>{IDENT})\s*\)\s*;'
        rf'\s*(?P<score>{IDENT})\s*=\s*(?P<table>{access})\s*\[\s*(?P=slot)\s*\]\s*;'
        rf'\s*if\s*\(\s*(?P<best>{IDENT})\s*<\s*(?P=score)\s*\)\s*{{'
        rf'\s*(?P=best)\s*=\s*(?P=score)\s*;\s*{IDENT}\s*=\s*(?P=slot)\s*;\s*}}'
        rf'\s*(?P=i)\+\+\s*;\s*}}\s*while\s*\(\s*(?P=i)\s*<\s*{IDENT}\s*\)\s*;'
    )
    results = []
    for loop in first.finditer(part.clean, part.opening + 1, part.end):
        call, i, score, table, slot = (loop[key] for key in ('callee', 'i', 'score', 'table', 'slot'))
        if call not in callees or not re.search(rf'\bs16\s*\*\s*{loop["field"]}\s*;', part.body):
            continue
        second = re.compile(
            rf'\bdo\s*{{\s*(?P<index>{IDENT})\s*=\s*\(u16\)\s*{call}\s*\(\s*\(u16\)\s*{i}\s*\)\s*;'
            rf'(?P<load>\s*{score}\s*=\s*(?P<read>{re.escape(table)}\s*\[\s*(?P=index)\s*\])\s*;)'
            rf'\s*{i}\+\+\s*;\s*{loop["best"]}\s*\+=\s*'
            rf'(?P<compare>\*\s*(?P<ptr>{IDENT})\s*==\s*{score})\s*;'
            rf'\s*}}\s*while\s*\(\s*{i}\s*<\s*{IDENT}\s*\)\s*;'
        ).search(part.clean, loop.end(), part.end)
        if not second:
            continue
        index, ptr = second['index'], second['ptr']
        if len({index, i, score, slot}) != 4 or not re.search(rf'\bs16\s*\*\s*{ptr}\s*;', part.body):
            continue
        grouped = re.match(rf'\s*s32\s+(?P<names>{IDENT}(?:\s*,\s*{IDENT})+)\s*;',
                           part.clean[part.opening+1:loop.start()])
        if not grouped:
            continue
        names = re.findall(IDENT, grouped['names'])
        if ({index, i, score, loop['best']} - set(names) or slot in names
                or re.search(rf'&\s*\(*\s*(?:{index}|{i}|{score})\b', part.body)):
            continue
        if re.search(rf'\b(?:{index}|{score})\b', part.clean[second.end():part.end]):
            continue
        if re.search(rf'\b{index}\b', part.clean[loop.start():loop.end()]):
            continue
        if re.search(rf'\b{index}\b', part.clean[loop.end():second.start()]):
            continue
        start, end = (part.opening + 1 + p for p in grouped.span('names'))
        decl_end = part.opening + 1 + grouped.end()
        # Keep the score in the same scope while giving it its own declaration.
        replacement = ', '.join(n for n in names if n != score)
        comparison = f'{second["read"]} == *{ptr}'
        edits = [(start, end, replacement), (decl_end, decl_end, f' s32 {score};'),
                 (*loop.span('decl'), ''), (*second.span('load'), ''), (*second.span('compare'), comparison)]
        edits.extend((hit.start(), hit.end(), index) for hit in
                     re.compile(rf'\b{slot}\b').finditer(part.clean, loop.start(), loop.end()))
        lhs_end = part.clean.index('=', loop.end('slot'), loop.end())
        edits.append((lhs_end + 1, lhs_end + 1, ' (u16)'))
        if all(source[a:b] == part.clean[a:b] for a, b, _ in edits):
            results.append((HALFWORD_INDEX, edit(source, edits)))
    return results[:2]
