"""Try an indexed byte read where a draft inferred a word-sized global."""

import re

from .integer_repair_support import IDENT, edit, view

_INDEXED = re.compile(
    rf'\*\(\s*&\s*(?P<table>{IDENT})\s*\+\s*\(\s*(?P<index>{IDENT})\s*&\s*0[xX][fF][fF]\s*\)\s*\)'
)


def variants(source, name, header, rows):
    part = view(source, name)
    if not part or re.search(r'\bvolatile\b', part.clean):
        return []
    matches = list(_INDEXED.finditer(part.body))
    if len(matches) != 1:
        return []
    hit = matches[0]
    table = hit['table']
    context = part.clean + '\n' + header
    if not re.search(rf'\bextern\s+(?:s32|u32|M2C_UNK|int)\s+{re.escape(table)}\s*;', context):
        return []
    symbol = re.escape(table)
    byte = re.compile(rf'lbu\s+\$\w+,\s*%lo\({symbol}\)\(\$\w+\)')
    word = re.compile(rf'lw\s+\$\w+,\s*%lo\({symbol}\)\(\$\w+\)')
    changes = [(left, right) for marker, left, right in rows if marker != ' ']
    if not any(byte.fullmatch(left) and word.fullmatch(right) for left, right in changes):
        return []
    if not any(not left and re.fullmatch(r'sll\s+\$(\w+),\s*\$\1,\s*(?:2|0x2)', right)
               for left, right in changes):
        return []
    start = part.opening + 1
    cast = f'*((u8 *)&{table} + ({hit["index"]} & 0xFF))'
    fixed = edit(source, [(start + hit.start(), start + hit.end(), cast)])
    return [('measured_indexed_byte_table', fixed)]
