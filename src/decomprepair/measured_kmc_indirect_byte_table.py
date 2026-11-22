"""Recover a byte read through a pointer stored in an inferred byte table."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, view

_READ = re.compile(
    rf'\*\(\s*s32\s*\*\s*\)\s*\*\(\s*(?P<table>{IDENT})\s*\+\s*'
    rf'\(\s*(?P<index>{IDENT})\s*\*\s*(?P<stride>{NUMBER})\s*\)\s*\)'
)


def variants(source, name, header, rows):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|goto|asm|__asm__)\b', part.clean):
        return []
    hits = list(_READ.finditer(part.body))
    if len(hits) != 1:
        return []
    hit = hits[0]
    symbol = re.escape(hit['table'])
    if not re.search(rf'\bextern\s+char\s+{symbol}\s*\[\s*\]\s*;', part.clean + '\n' + header):
        return []
    target = [left for _, left, _ in rows if left]
    direct = re.compile(rf'lw\s+\$(?P<reg>\w+),\s*%lo\({symbol}\)\(\$\w+\)')
    found = False
    for pos, line in enumerate(target[:-1]):
        load = direct.fullmatch(line)
        if load and re.fullmatch(rf'lbu\s+\${load["reg"]},\s*(?:0|0x0)?\(\${load["reg"]}\)', target[pos+1]):
            found = True
            break
    changed_right = [right for marker, _, right in rows if marker != ' ' and right]
    wrong_byte = re.compile(rf'lb\s+\$\w+,\s*%lo\({symbol}\)\(\$\w+\)')
    if not found or not any(wrong_byte.fullmatch(line) for line in changed_right):
        return []
    start = part.opening + 1
    replacement = f'**(u8 **)({hit["table"]} + ({hit["index"]} * {hit["stride"]}))'
    change = (start + hit.start(), start + hit.end(), replacement)
    result = [('measured_indirect_byte_table', edit(source, [change]))]
    # GCC may schedule the return-address save differently after changing the loads.
    assignments = list(re.finditer(
        rf'\b{re.escape(hit["index"])}\s*=\s*{IDENT}\s*&\s*(?:0[xX][fF]{{4}}|65535)\s*;', part.body))
    changed_left = [left for marker, left, _ in rows if marker != ' ' and left]
    if (len(assignments) == 1
            and any(re.fullmatch(r'sw\s+\$ra,\s*(?:0x[0-9a-f]+|\d+)\(\$sp\)', line) for line in changed_left)
            and any(re.fullmatch(r'sw\s+\$ra,\s*(?:0x[0-9a-f]+|\d+)\(\$sp\)', line) for line in changed_right)):
        assignment = assignments[0]
        scope = (start + assignment.start(), start + assignment.end(),
                 'do { '+assignment[0]+' } while (0);')
        result.append(('measured_indirect_byte_table_scope', edit(source, [change, scope])))
    return result
