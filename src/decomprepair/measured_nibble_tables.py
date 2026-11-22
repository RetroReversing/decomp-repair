"""Recover byte and halfword table widths from a nibble dispatch target."""

import re

from .integer_repair_support import edit, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines
from .pattern_repairs import close

_SOURCE = _shape('''
    u32 @upper; u8 @value;
    @value = *(&@bytes + M2C_FIELD(&@record, u8 *, 0));
    @upper = @value >> 4;
    if ((@value & 0xF) == 6) {
        M2C_FIELD(&@record, u16 *, 5) = (u16) *(&@tablea + (@upper * 2));
    } else {
        @outa = *(&@tableb + (@upper * 2));
    }
    @outb = *(&@tablec + ((@value & 0xF) * 2));
''')


def variants(source, name, header, rows):
    if not 20 <= len(rows) <= 45:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    candidate = '\n'.join(normalized_integer_lines(right for _, _, right in rows if right))
    if (target.count('sll $v0, $v0, 1') != 3 or candidate.count('sll $v0, $a1, 3') != 2
            or 'andi $v1, $a0, 15' not in target or 'srl $v0, $a0, 4' not in target):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end or re.search(r'\b(?:volatile|asm|__asm__|__LINE__)\b', part.clean):
        return []
    part.end = end
    draft = _SOURCE.fullmatch(' '.join(part.body.split()))
    if not draft or not re.search(rf'\bvoid\s+{re.escape(name)}\s*\(\s*void\s*\)\s*$', part.clean[:part.opening]):
        return []
    keys = ('bytes', 'record', 'tablea', 'tableb', 'tablec')
    if len({draft[key] for key in keys}) != len(keys):
        return []
    edits = []
    for key in keys:
        symbol = draft[key]
        if (re.search(rf'\b{re.escape(symbol)}\b', header)
                or f'%hi({symbol})' not in target or f'%lo({symbol})' not in target):
            return []
        declaration = re.search(rf'\bextern\s+M2C_UNK\s+{re.escape(symbol)}\s*;', part.clean[:part.opening])
        if not declaration or source[declaration.start():declaration.end()] != declaration[0]:
            return []
        kind = 'u8' if key in ('bytes', 'record') else 'u16'
        edits.append((declaration.start(), declaration.end(), f'extern {kind} {symbol}[];'))
    for key in ('outa', 'outb'):
        if (f'%hi({draft[key]})' not in target
                or not re.search(rf'\bextern\s+u16\s+{re.escape(draft[key])}\s*;', part.clean[:part.opening])):
            return []
    original = source[part.opening + 1:part.end - 1]
    if '/*' in original or '//' in original or '#' in original:
        return []
    body = (f'\n    u8 {draft["value"]};\n\n'
            f'    {draft["value"]} = {draft["bytes"]}[{draft["record"]}[0]];\n'
            f'    if (({draft["value"]} & 0xF) == 6) {{\n'
            f'        *(u16 *) ({draft["record"]} + 5) = {draft["tablea"]}[{draft["value"]} >> 4];\n'
            f'    }} else {{\n        {draft["outa"]} = {draft["tableb"]}[{draft["value"]} >> 4];\n'
            f'    }}\n    {draft["outb"]} = {draft["tablec"]}[{draft["value"]} & 0xF];\n')
    edits.append((part.opening + 1, part.end - 1, body))
    return [('measured_nibble_tables', edit(source, edits))]
