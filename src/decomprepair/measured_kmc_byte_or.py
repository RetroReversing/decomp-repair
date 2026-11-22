"""Expose byte truncation before a measured complement-and-OR sequence."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import normalized_integer_lines
from .narrow_store_repairs import declared
from .target_memory_repairs import _statement

FIELD = rf'M2C_FIELD\s*\(\s*{IDENT}\s*,\s*u8\s*\*\s*,\s*{NUMBER}\s*\)'
ASSIGN = re.compile(rf'\b(?P<out>{IDENT})\s*=\s*(?P<expr>{FIELD}\s*\|\s*~\s*{FIELD})\s*\|\s*(?P<mask>{NUMBER})\s*;')


def variants(source, name, header, rows):
    target = normalized_integer_lines(left for _, left, _ in rows if left)
    candidate = normalized_integer_lines(right for _, _, right in rows if right)
    if not any(line.startswith('nor ') for line in target) or not any(line.startswith('or ') for line in target):
        return []
    masks = set()
    for tag, left, right in rows:
        if tag == ' ':
            continue
        for line in normalized_integer_lines((left,)):
            if m := re.fullmatch(r'ori \$\w+, \$\w+, (\d+)',line):
                value = int(m[1])
                if 128 <= value <= 255 and any(re.fullmatch(rf'addiu \$\w+, \$zero, {value-256}',op)
                                                for op in candidate):
                    masks.add(value)
    if not masks:
        return []
    part = view(source,name)
    if not part:
        return []
    for hit in ASSIGN.finditer(part.clean,part.opening+1,part.end-1):
        if integer(hit['mask']) not in masks or not _statement(part,hit.start()):
            continue
        if (declared(part,hit['out'],hit.start(),header)!=('u8','')
                or re.search(rf'^\s*#\s*define\s+{re.escape(hit["out"])}\b',header+'\n'+source,re.M)):
            continue
        expression = source[hit.start('expr'):hit.end('expr')]
        return [('byte_or_complement_narrow',edit(source,[(hit.start('expr'),hit.end('expr'),f'(u8)({expression})')]))]
    return []
