"""Stage two signed-halfword lookups used in a fixed-point interpolation."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, locals_for, view
from .mips import normalized_integer_lines

FAMILY = 'measured_interpolation_calls'


def variants(source, name, header, rows):
    part = view(source, name)
    context = source + '\n' + header
    if (not part or re.search(r'\b(?:volatile|asm|__asm__|setjmp|longjmp)\b', part.clean)
            or re.search(r'\btypedef\b[^;]*\bvolatile\b[^;]*\b(?:s16|s32)\s*;', header)
            or '__repair_interp_' in context):
        return []
    pattern = re.compile(
        rf'(?P<low>{IDENT})\s*=\s*(?P<call>{IDENT})\s*\(\s*(?P<index>{IDENT})\s*\)\s*;\s*'
        rf'return\s*\(\s*s16\s*\)\s*\(\s*(?P=low)\s*\+\s*\(\s*\(\s*\(\s*'
        rf'(?P<input>{IDENT})\s*&\s*(?P<mask>{NUMBER})\s*\)\s*\*\s*\(\s*'
        rf'(?P=call)\s*\(\s*(?P=index)\s*\+\s*1\s*\)\s*-\s*(?P=low)\s*\)\s*\)\s*/\s*'
        rf'(?P<divisor>{NUMBER})\s*\)\s*\)\s*;')
    matches = list(pattern.finditer(part.clean, part.opening + 1, part.end))
    if len(matches) != 1:
        return []
    match = matches[0]
    low, call, index, input_ = (match[k] for k in ('low', 'call', 'index', 'input'))
    decls = {d['name']: d['type'] for d in locals_for(part)}
    signature = part.clean[part.clean.rfind(name, 0, part.opening):part.opening]
    if (decls.get(low) != 's16' or decls.get(index) != 's32' or len({low, index, input_}) != 3
            or not re.search(rf'\bs32\s+{re.escape(input_)}\s*(?:,|\))', signature)
            or re.search(rf'&\s*(?:{re.escape(low)}|{re.escape(index)}|{re.escape(input_)})\b', part.body)
            or re.search(r'/[*/]|#', source[match.start():match.end()])):
        return []
    prefix = part.clean[part.opening + 1:match.start()].rstrip()
    if prefix and prefix[-1] not in ';{}':
        return []
    # A real, signed-halfword-returning function is required: a macro can
    # see locals or evaluate its argument more than once.
    if (not re.search(rf'\bs16\s+{re.escape(call)}\s*\(\s*(?:s32\s*(?:{IDENT})?\s*)?\)\s*;', context)
            or re.search(rf'\b{re.escape(call)}\s*\([^;{{}}]*\)\s*\{{', part.clean)):
        return []
    macros = re.findall(r'(?m)^\s*#\s*define[^\n]*', context)
    if any(re.search(rf'\b(?:{re.escape(low)}|{re.escape(index)}|{re.escape(input_)}|{re.escape(call)})\b', line)
           for line in macros):
        return []
    lines = [normalized_integer_lines((a, b)) for _, a, b in rows]
    left = [a for a, _ in lines if a]
    right = [b for _, b in lines if b]
    calls = [[i for i, line in enumerate(seq) if line == f'jal {call}'] for seq in (left, right)]
    if any(len(found) != 2 for found in calls):
        return []
    target_first, target_second = calls[0]
    _, cand_second = calls[1]
    shifts = [re.fullmatch(r'sll (\$s[0-7]), \$v0, 16', line)
              for line in left[target_first + 1:target_second]]
    regs = {m[1] for m in shifts if m}
    if not any(f'move {reg}, $v0' in right[cand_second + 1:]
               and any(re.fullmatch(rf'sll \$\w+, {re.escape(reg)}, 16', line)
                       for line in right[cand_second + 1:]) for reg in regs):
        return []
    mask, divisor = (source[slice(*match.span(k))] for k in ('mask', 'divisor'))
    staged = (f'__repair_interp_first = {call}({index});\n    {low} = __repair_interp_first;\n'
              f'    __repair_interp_delta = {call}({index} + 1) - {low};\n'
              f'    return (s16) ({low} + ((({input_} & {mask}) * __repair_interp_delta) / {divisor}));')
    return [(FAMILY, edit(source, [(part.opening + 1, part.opening + 1,
                                    '\n    s32 __repair_interp_first;\n    s32 __repair_interp_delta;'),
                                   (match.start(), match.end(), staged)]))]
