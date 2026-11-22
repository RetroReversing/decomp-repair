"""Recover IDO's repeated index and registered owner for a final update."""

import re

from .integer_repair_support import IDENT, edit, view

NUM = r'(?:0x[0-9a-fA-F]+|[0-9]+)'
TARGET_INDEX = re.compile(
    rf'lw \$t7, (?P<stack>{NUM})\(\$sp\)\nlw \$t9, (?P<field>{NUM})\(\$t7\)\n'
    r'sll \$t6, \$t9, 2\naddu \$t6, \$t6, \$t9\nsll \$t6, \$t6, 3\n'
    r'addu \$t0, \$t7, \$t6\nsw \$t9, '
)
CANDIDATE_INDEX = re.compile(
    rf'lw \$t7, (?P<stack>{NUM})\(\$sp\)\nlw \$s0, (?P<field>{NUM})\(\$t7\)\n'
    rf'lw \$t9, (?P=stack)\(\$sp\)\nsll \$t6, \$s0, 2\naddu \$t6, \$t6, \$s0\n'
    r'sll \$t6, \$t6, 3\naddu \$t0, \$t9, \$t6\nsw \$s0, '
)
TARGET_UPDATE = re.compile(
    rf'lw \$s0, (?P<stack>{NUM})\(\$sp\)\nlw \$t3, (?P<field>{NUM})\(\$s0\)\n'
    rf'addiu \$t5, \$t3, 1\nsw \$t5, (?P=field)\(\$s0\)'
)
CANDIDATE_UPDATE = re.compile(
    rf'lw \$t3, (?P<stack>{NUM})\(\$sp\)\nlw \$t5, (?P<field>{NUM})\(\$t3\)\n'
    rf'addiu \$t8, \$t5, 1\nsw \$t8, (?P=field)\(\$t3\)'
)


def variants(source, name, header, rows):
    target = '\n'.join(' '.join(left.split()) for _, left, _ in rows if left)
    candidate = '\n'.join(' '.join(right.split()) for _, _, right in rows if right)
    evidence = [TARGET_INDEX.search(target), CANDIDATE_INDEX.search(candidate),
                TARGET_UPDATE.search(target), CANDIDATE_UPDATE.search(candidate)]
    if any(x is None for x in evidence):
        return []
    if any((x['stack'], x['field']) != (evidence[0]['stack'], evidence[0]['field']) for x in evidence[1:]):
        return []
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean):
        return []
    pattern = re.compile(
        rf'(?P<temp>{IDENT})\s*=\s*(?P<owner>{IDENT})\s*->\s*(?P<count>{IDENT})\s*;\s*'
        rf'(?P=owner)\s*->\s*(?P<array>{IDENT})\s*\[\s*(?P=temp)\s*\]\s*'
        rf'\.\s*(?P<member>{IDENT})\s*=\s*(?P=temp)\s*;'
    )
    matches = list(pattern.finditer(part.body))
    if len(matches) != 1:
        return []
    m = matches[0]
    temp, owner, count = m['temp'], m['owner'], m['count']
    decl = re.search(rf'\bregister\s+s32\s+{re.escape(temp)}\s*;', part.body)
    if not decl or len(re.findall(rf'\b{re.escape(temp)}\b', part.body)) != 4:
        return []
    signature = re.search(rf'\b(?P<type>{IDENT})\s*\*\s*{re.escape(owner)}\b', part.clean[:part.opening])
    update = list(re.finditer(rf'\b{re.escape(owner)}\s*->\s*{re.escape(count)}\s*\+=\s*1\s*;', part.body))
    if not signature or len(update) != 1 or update[0].start() <= m.end():
        return []
    if re.search(rf'(?m)^\s*#\s*define\s+(?:{re.escape(owner)}|{re.escape(count)}|{re.escape(temp)})\b',
                 source + '\n' + header):
        return []
    if re.search(rf'\bvolatile\b[^;{{}}]*\b{re.escape(count)}\b', header):
        return []
    tmp = '__repair_owner'
    if re.search(rf'\b{tmp}\b', source + '\n' + header):
        return []
    if any('/*' in source[part.opening + 1 + x.start():part.opening + 1 + x.end()]
           or '//' in source[part.opening + 1 + x.start():part.opening + 1 + x.end()] for x in (m, update[0])):
        return []
    replacement = f'{owner}->{m["array"]}[{owner}->{count}].{m["member"]} = {owner}->{count};'
    edits = [(part.opening + 1 + decl.start(), part.opening + 1 + decl.end(),
              f'register {signature["type"]} *{tmp};'),
             (part.opening + 1 + m.start(), part.opening + 1 + m.end(), replacement),
             (part.opening + 1 + update[0].start(), part.opening + 1 + update[0].end(),
              f'{tmp} = {owner};\n    {tmp}->{count} += 1;')]
    return [('measured_ido_index_update', edit(source, edits))]
