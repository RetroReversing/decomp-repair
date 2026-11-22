"""Try the halfword flag access shown by a target for an inferred byte table."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, view

_FLAG = re.compile(
    rf'(?P<lhs>\*\(\s*(?P<table>{IDENT})\s*\+\s*(?P<index>{IDENT})\s*\))\s*=\s*'
    rf'(?P<rhs>\*\(\s*(?P=table)\s*\+\s*(?P=index)\s*\))\s*\|\s*{NUMBER}\s*;'
)


def variants(source, name, header, rows):
    part = view(source, name)
    if not part or re.search(r'\bvolatile\b', part.clean):
        return []
    matches = list(_FLAG.finditer(part.body))
    if len(matches) != 1:
        return []
    hit = matches[0]
    table = hit['table']
    if not re.search(rf'\bextern\s+char\s+{re.escape(table)}\s*\[\s*\]\s*;', part.clean + '\n' + header):
        return []
    symbol = re.escape(table)
    left_load = re.compile(rf'\blhu\s+\$\w+,\s*%lo\({symbol}\)\(\$\w+\)')
    right_load = re.compile(rf'\blbu\s+\$\w+,\s*%lo\({symbol}\)\(\$\w+\)')
    left_store = re.compile(rf'\bsh\s+\$\w+,\s*%lo\({symbol}\)\(\$\w+\)')
    right_store = re.compile(rf'\bsb\s+\$\w+,\s*%lo\({symbol}\)\(\$\w+\)')
    changed = [(left, right) for marker, left, right in rows if marker != ' ']
    if (not any(left_load.fullmatch(left) and right_load.fullmatch(right) for left, right in changed)
            or not any(left_store.fullmatch(left) and right_store.fullmatch(right) for left, right in changed)):
        return []
    start = part.opening + 1
    cast = f'*(u16 *)({table} + {hit["index"]})'
    fixed = edit(source, [(start + hit.start('lhs'), start + hit.end('lhs'), cast),
                          (start + hit.start('rhs'), start + hit.end('rhs'), cast)])
    return [('measured_halfword_flag_table', fixed)]
