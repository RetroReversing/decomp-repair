"""Recover a variable-byte accumulator from a draft with a missing initial value."""

import re

from .integer_repair_support import IDENT, edit, view
from .mips import normalized_integer_lines

_ARGS = rf'(?:{IDENT}(?:\s*,\s*{IDENT})*)?'
_BODY = re.compile(rf'''
    \s*s32\s+(?P<first>{IDENT})\s*;\s*s32\s+(?P<byte>{IDENT})\s*;
    \s*s32\s+(?P<acc>{IDENT})\s*;\s*s32\s+(?P<unused>{IDENT})\s*;
    \s*(?P=first)\s*=\s*(?P<call>{IDENT})\s*\(\s*(?P<firstargs>{_ARGS})\s*\)\s*&\s*0[xX][fF][fF]\s*;
    \s*(?P=unused)\s*=\s*(?P=first)\s*;
    \s*if\s*\(\s*(?P=first)\s*&\s*0[xX]80\s*\)\s*{{
        \s*(?P=acc)\s*=\s*(?P=first)\s*&\s*0[xX]7[fF]\s*;
        \s*do\s*{{
            \s*(?P=byte)\s*=\s*(?P=call)\s*\(\s*(?P<args>{_ARGS})\s*\)\s*&\s*0[xX][fF][fF]\s*;
            \s*(?P=acc)\s*=\s*\(\s*(?P=acc)\s*<<\s*7\s*\)\s*\+\s*\(\s*(?P=byte)\s*&\s*0[xX]7[fF]\s*\)\s*;
        \s*}}\s*while\s*\(\s*(?P=byte)\s*&\s*0[xX]80\s*\)\s*;
        \s*(?P=unused)\s*=\s*(?P=acc)\s*;
    \s*}}\s*return\s+(?P=acc)\s*;\s*
''', re.X)


def variants(source, name, header, rows):
    changed = [normalized_integer_lines((left, right)) for marker, left, right in rows if marker != ' ']
    if (('andi $s0, $v0, 255', 'move $v1, $v0') not in changed
            or ('andi $v0, $v0, 255', '') not in changed):
        return []
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|goto|asm|__asm__)\b', part.clean):
        return []
    body = _BODY.fullmatch(part.body)
    if not body or len({body[key] for key in ('first', 'byte', 'acc', 'unused')}) != 4:
        return []
    signature = re.search(rf'\bs32\s+{re.escape(name)}\s*\([^;{{}}]*\)\s*$', part.clean[:part.opening])
    if not signature:
        return []
    names = [body[key] for key in ('first', 'byte', 'acc', 'unused', 'call')]
    if any(re.search(rf'(?m)^\s*#\s*define\s+{re.escape(item)}\b', part.clean + '\n' + header) for item in names):
        return []
    first_args = source[part.opening + 1 + body.start('firstargs'):part.opening + 1 + body.end('firstargs')]
    args = source[part.opening + 1 + body.start('args'):part.opening + 1 + body.end('args')]
    acc, byte, call = body['acc'], body['byte'], body['call']
    fixed_body = (f'\n    s32 {byte};\n    s32 {acc};\n\n'
                  f'    {acc} = (u8) {call}({first_args});\n'
                  f'    if ({acc} & 0x80) {{\n        {acc} &= 0x7F;\n        do {{\n'
                  f'            {byte} = (u8) {call}({args});\n'
                  f'            {acc} = ({acc} << 7) + ({byte} & 0x7F);\n'
                  f'        }} while ({byte} & 0x80);\n    }}\n    return {acc};\n')
    return [('measured_varbyte_initialization', edit(source, [(part.opening + 1, part.end - 1, fixed_body)]))]
