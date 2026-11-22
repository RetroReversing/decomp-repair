"""Place a bounded table index in each branch when KMC needs its own register."""

import re

from .integer_repair_support import IDENT, edit, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

_SOURCE = re.compile(
    rf'(?P<assign>(?P<index>{IDENT})\s*=\s*(?P<input>{IDENT})\s*&\s*0xFF\s*;)\s*'
    rf'if\s*\(\s*(?P<guard>{IDENT})\s*==\s*1\s*\)\s*\{{\s*'
    rf'(?P<first>(?P<result>{IDENT})\s*=\s*\*\(\s*(?P<tableone>{IDENT})\s*\+\s*(?P=index)\s*\)\s*;)\s*'
    rf'\}}\s*else\s*\{{\s*(?P<second>(?P=result)\s*=\s*\*\(\s*(?P<tabletwo>{IDENT})\s*\+\s*(?P=index)\s*\)\s*;)\s*\}}'
)


def variants(source, name, header, rows):
    if len(rows) != 28:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    changes = [normalized_integer_lines((left, right)) for marker, left, right in rows if marker != ' ']
    if (('andi $v0, $a0, 255', 'andi $a0, $a0, 255') not in changes
            or ('addu $a1, $a1, $v0', 'addu $a1, $a1, $a0') not in changes):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    body = part.body
    draft = _SOURCE.search(body)
    if not draft or re.search(r'\bvolatile\b', part.clean):
        return []
    index, input_ = draft['index'], draft['input']
    if (not re.search(rf'\bs32\s+{re.escape(index)}\s*;', body)
            or not re.search(rf'\bu8\s+{re.escape(input_)}\s*;', body)
            or not re.search(rf'\b{re.escape(input_)}\s*=\s*{IDENT}\s*&\s*7\s*;', body[:draft.start()])
            or not re.search(rf'\bextern\s+s16\s+{re.escape(draft["guard"])}\s*;', part.clean[:part.opening])
            or any(f'%hi({draft[key]})' not in target for key in ('guard', 'tableone', 'tabletwo'))):
        return []
    start = part.opening + 1
    fixed = edit(source, [(start + draft.start('assign'), start + draft.end('assign'), ''),
                          (start + draft.start('first'), start + draft.start('first'), draft['assign'] + '\n                '),
                          (start + draft.start('second'), start + draft.start('second'), draft['assign'] + '\n                ')])
    return [('measured_split_table_index', fixed)]
