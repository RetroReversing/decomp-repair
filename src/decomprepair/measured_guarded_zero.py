"""Sink a local zero initialization into its measured call-guarded block."""

import re

from .integer_repair_support import IDENT, edit, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

TARGET = re.compile(
    rf'jal (?P<callee>{IDENT})\nsw \$s0, \d+\(\$sp\)\n'
    rf'beqz \$v0, \d+\nmove \$s1, \$zero'
)


def variants(source, name, header, rows):
    target, candidate = ('\n'.join(normalized_integer_lines(row[side] for row in rows if row[side]))
                         for side in (1, 2))
    measured = TARGET.search(target)
    if not measured or not re.search(rf'jal {re.escape(measured["callee"])}\nsw \$s0, \d+\(\$sp\)\n'
                                     r'beqz \$v0, \d+\nnop', candidate):
        return []
    if not re.search(r'move \$s1, \$zero\n', candidate):
        return []
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__|goto|setjmp|longjmp)\b|(?<![?:]):(?!:)', part.body):
        return []
    init = re.compile(rf'\b(?P<local>{IDENT})\s*=\s*0\s*;\s*if\s*\(')
    for m in init.finditer(part.body):
        local = m['local']
        cond_open = part.opening + 1 + m.end() - 1
        cond_end = close(part.clean, cond_open)
        if not cond_end:
            continue
        cond = part.clean[cond_open + 1:cond_end - 1]
        if re.search(rf'\b{re.escape(local)}\b', cond) or not re.search(rf'\b{re.escape(measured["callee"])}\s*\(', cond):
            continue
        brace = re.match(r'\s*\{', part.clean[cond_end:])
        if not brace:
            continue
        opening = cond_end + brace.end() - 1
        end = close(part.clean, opening, '{', '}')
        if not end or not re.search(rf'\b{re.escape(local)}\b', part.clean[opening + 1:end - 1]):
            continue
        if re.search(rf'\b{re.escape(local)}\b', part.clean[end:part.end - 1]):
            continue
        decls = list(re.finditer(rf'\b(?:s32|u32|int)\s+{re.escape(local)}\s*;', part.body[:m.start()]))
        if len(decls) != 1 or re.search(rf'&\s*{re.escape(local)}\b', part.body):
            continue
        if re.search(rf'\b{re.escape(local)}\b', part.body[decls[0].end():m.start()]):
            continue
        if re.search(rf'(?m)^\s*#\s*define\s+{re.escape(local)}\b', source + '\n' + header):
            continue
        start = part.opening + 1 + m.start()
        stop = start + re.match(rf'{re.escape(local)}\s*=\s*0\s*;', part.clean[start:]).end()
        if source[start:stop] != part.clean[start:stop]:
            continue
        # A non-escaped local zero is unobservable on the skipped path, even
        # when the guard itself calls code; the target initializes it after that call.
        return [('measured_guarded_zero', edit(source, [
            (start, stop, ''),
            (opening + 1, opening + 1, f'\n        {local} = 0;'),
        ]))]
    return []
