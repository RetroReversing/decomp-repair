"""Try unsigned indexed byte reads when the target disagrees with signed drafts."""

import re

from . import target_call_arity_repairs
from .integer_repair_support import IDENT, NUMBER, edit, view

_READ = re.compile(
    rf'(?P<read>\*\(\s*(?P<table>{IDENT})\s*\+\s*(?P<index>{IDENT})\s*\))\s*\|\s*{NUMBER}'
)


def variants(source, name, header, rows, asm):
    part = view(source, name)
    if not part or re.search(r'\bvolatile\b', part.clean):
        return []
    matches = list(_READ.finditer(part.body))
    if len(matches) != 1:
        return []
    hit = matches[0]
    symbol = re.escape(hit['table'])
    if not re.search(rf'\bextern\s+char\s+{symbol}\s*\[\s*\]\s*;', part.clean + '\n' + header):
        return []
    unsigned = re.compile(rf'lbu\s+\$\w+,\s*%lo\({symbol}\)\(\$\w+\)')
    signed = re.compile(rf'lb\s+\$\w+,\s*%lo\({symbol}\)\(\$\w+\)')
    if not any(marker != ' ' and unsigned.fullmatch(left) and signed.fullmatch(right)
               for marker, left, right in rows):
        return []
    start = part.opening + 1
    fixed = edit(source, [(start + hit.start('read'), start + hit.end('read'), '(u8) '+hit['read'])])
    result = [('measured_unsigned_indexed_byte', fixed)]
    # The arity rule is speculative too; the judge accepts only an exact result.
    result.extend(('measured_unsigned_indexed_byte_arity', candidate)
                  for _, candidate in target_call_arity_repairs.variants(fixed, name, asm))
    return result
