"""Copy an unchanged pointer for a measured final call from a saved register."""

import re

from .integer_repair_support import IDENT, edit, view
from .mips import normalized_integer_lines


def variants(source, name, header, rows):
    target, candidate = ('\n'.join(normalized_integer_lines(row[side] for row in rows if row[side]))
                         for side in (1, 2))
    if not re.search(r'move \$s0, \$a0\n[^\n]*\nmove \$s1, \$s0', target):
        return []
    call = re.search(rf'jal (?P<callee>{IDENT})\nmove \$a0, \$s1', target)
    if not call or not re.search(rf'jal {re.escape(call["callee"])}\nmove \$a0, \$s0', candidate):
        return []
    part = view(source, name)
    if not part:
        return []
    signature = re.search(rf'\bs32\s+{re.escape(name)}\s*\(\s*void\s*\*\s*(?P<arg>{IDENT})\s*\)\s*$',
                          part.clean[:part.opening])
    if not signature:
        return []
    arg, callee = signature['arg'], call['callee']
    if arg == callee or re.search(r'\b__repair_saved_pointer\b', part.clean + '\n' + header):
        return []
    if re.search(rf'(?m)^\s*#\s*define\s+(?:{re.escape(arg)}|{re.escape(callee)})\b', source + '\n' + header):
        return []
    if re.search(rf'&\s*{re.escape(arg)}\b|(?:\+\+|--)\s*{re.escape(arg)}\b|'
                 rf'\b{re.escape(arg)}\s*(?:[+*/&|^-]?=(?!=)|\+\+|--)', part.body):
        return []
    returns = list(re.finditer(rf'\breturn\s+{re.escape(callee)}\s*\(\s*(?P<arg>{re.escape(arg)})\s*\)\s*;', part.body))
    if len(returns) != 1:
        return []
    # The pointer is never reassigned or exposed by address, so this preserves
    # the value while giving the final call its own measured saved-register life.
    pos = part.opening + 1
    m = returns[0]
    return [('measured_saved_pointer_copy', edit(source, [
        (pos, pos, f'\n    void *__repair_saved_pointer = {arg};'),
        (pos + m.start('arg'), pos + m.end('arg'), '__repair_saved_pointer'),
    ]))]
