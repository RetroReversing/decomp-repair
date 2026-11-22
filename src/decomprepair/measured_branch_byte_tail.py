"""Distribute a measured shared byte store into both selecting arms."""

import re

from .branch_tail_distribution import chain
from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import normalized_integer_lines

STORE = re.compile(rf'M2C_FIELD\s*\(\s*(?P<obj>{IDENT})\s*,\s*(?:s8|u8)\s*\*\s*,\s*'
                   rf'(?P<offset>{NUMBER})\s*\)\s*=\s*(?P<value>{NUMBER})\s*;')

TARGET = re.compile(
    r'addiu \$v0, \$zero, (?P<other>\d+)\nsb \$v0, (?P<otheroff>\d+)\(\$a0\)\n'
    r'j [^\n]+\naddiu \$v0, \$zero, (?P<tail>\d+)'
)


def variants(source, name, header, rows):
    target, candidate = ('\n'.join(normalized_integer_lines(row[side] for row in rows if row[side]))
                         for side in (1, 2))
    witness = TARGET.search(target)
    if not witness or witness['other'] == witness['tail']:
        return []
    if not re.search(rf'j [^\n]+\naddiu \$v0, \$zero, {witness["other"]}\b', candidate):
        return []
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__|goto|setjmp|longjmp)\b', part.body):
        return []
    signature = re.search(rf'\bvoid\s+{re.escape(name)}\s*\(\s*void\s*\*\s*(?P<obj>{IDENT})\s*\)\s*$',
                          part.clean[:part.opening])
    if not signature:
        return []
    obj = signature['obj']
    macros = set(re.findall(r'(?m)^\s*#\s*define\s+(' + IDENT + r')\b', source + '\n' + header))
    if obj in macros:
        return []
    for hit in re.finditer(r'\bif\s*\(', part.body):
        start = part.opening + 1 + hit.start()
        found = chain(part, start)
        if not found or len(found[0]) != 2:
            continue
        arms, end = found
        tail = STORE.match(part.clean, end + len(part.clean[end:]) - len(part.clean[end:].lstrip()))
        if not tail or tail['obj'] != obj or integer(tail['value']) != int(witness['tail']):
            continue
        offset = integer(tail['offset'])
        if f'sb $v0, {offset}($a0)' not in target or f'sb $v0, {offset}($a0)' not in candidate:
            continue
        arm_stores = []
        for a, b in arms:
            contents = part.clean[a + 1:b - 1]
            hits = list(STORE.finditer(contents))
            if not hits or STORE.sub('', contents).strip() or any(x['obj'] != obj for x in hits):
                break
            arm_stores.append(hits)
        else:
            if not any(integer(x['offset']) == int(witness['otheroff']) and integer(x['value']) == int(witness['other'])
                       for x in arm_stores[0]):
                continue
            text = source[tail.start():tail.end()]
            if text != part.clean[tail.start():tail.end()]:
                continue
            return [('measured_branch_byte_tail', edit(source, [
                (arms[0][1] - 1, arms[0][1] - 1, '\n                ' + text + '\n            '),
                (arms[1][1] - 1, arms[1][1] - 1, '\n                ' + text + '\n            '),
                (tail.start(), tail.end(), ''),
            ]))]
    return []
