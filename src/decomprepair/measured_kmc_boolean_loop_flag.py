"""Try an explicit byte flag and two boolean tests in a linked-list loop."""

import re

from .integer_repair_support import IDENT, edit, view
from .mips import normalized_integer_lines

_CONDITION = re.compile(rf'\bwhile\s*\(\s*(?P<flag>{IDENT})\s*&\s*\(\s*(?P<cursor>{IDENT})\s*!=\s*NULL\s*\)\s*\)')


def variants(source, name, header, rows):
    changed = [normalized_integer_lines((left, right)) for marker, left, right in rows if marker != ' ']
    if not any(left == 'sltu $v0, $zero, $s0' and right.startswith('beqz $s0, ')
               for left, right in changed):
        return []
    if ('and $v0, $s2, $v0', 'andi $v0, $s2, 1') not in changed:
        return []
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|goto|asm|__asm__)\b', part.clean):
        return []
    conditions = list(_CONDITION.finditer(part.body))
    if len(conditions) != 1:
        return []
    condition = conditions[0]
    flag, cursor = condition['flag'], condition['cursor']
    if flag == cursor or re.search(rf'\b{re.escape(flag)}\b', header + '\n' + part.clean[:part.opening]):
        return []
    if re.search(rf'(?m)^\s*#\s*define\s+{re.escape(flag)}\b', part.clean + '\n' + header):
        return []
    flag_word = re.escape(flag)
    decls = list(re.finditer(rf'\bs32\s+{flag_word}\s*;', part.body))
    assigns = list(re.finditer(rf'\b{flag_word}\s*=\s*([01])\s*;', part.body))
    if (len(decls) != 1 or sorted(m[1] for m in assigns) != ['0', '1']
            or len(re.findall(rf'\b{flag_word}\b', part.body)) != 4):
        return []
    start = part.opening + 1
    decl = decls[0]
    fixed = edit(source, [(start + decl.start(), start + decl.start() + 3, 'u8'),
                          (start + condition.start(), start + condition.end(),
                           f'while (({cursor} != NULL) & ({flag} != 0))')])
    return [('measured_boolean_loop_flag', fixed)]
