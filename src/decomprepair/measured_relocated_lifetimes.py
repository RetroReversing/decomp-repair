"""Repairs for separately relocated byte addresses and repeated pointer loads."""

import re

from .integer_repair_support import IDENT, NUMBER, calls, edit, integer, split_args, view
from .mips_returns import instructions

_INDEX = re.compile(
    r'(?m)^andi \$a0, \$a0, 65535\nsll \$v0, \$a0, 1\naddu \$v0, \$v0, \$a0\n'
    r'sll \$v0, \$v0, 3\naddu \$v0, \$v0, \$a0\nsll \$v0, \$v0, 2\n'
    rf'lui \$v1, %hi\((?P<symbol>{IDENT})\)\naddiu \$v1, \$v1, %lo\((?P=symbol)\)\n'
    r'addu \$s0, \$v0, \$v1$'
)
_CALLBACK_RESET = re.compile(
    rf'(?m)^lui \$v1, %hi\((?P<base>{IDENT})\)\nlw \$v1, %lo\((?P=base)\)\(\$v1\)\n'
    r'sb \$zero, (?P<first>\d+)\(\$v1\)\n'
    r'lui \$a0, %hi\((?P=base)\)\nlw \$a0, %lo\((?P=base)\)\(\$a0\)\n'
    rf'lui \$v0, %hi\((?P<handler1>{IDENT})\)\naddiu \$v0, \$v0, %lo\((?P=handler1)\)\n'
    r'sw \$v0, (?P<slot1>\d+)\(\$v1\)\n'
    rf'lui \$v0, %hi\((?P<handler2>{IDENT})\)\naddiu \$v0, \$v0, %lo\((?P=handler2)\)\n'
    r'sw \$v0, (?P<slot2>\d+)\(\$v1\)\n'
    r'addiu \$v0, \$zero, -1\nsb \$v0, (?P<second>\d+)\(\$a0\)\n'
    r'lui \$v1, %hi\((?P=base)\)\nlw \$v1, %lo\((?P=base)\)\(\$v1\)\n'
    r'(?:addu \$v0, \$zero, \$zero|move \$v0, \$zero)\nsb \$zero, (?P<last>\d+)\(\$v1\)$'
)


_CONTEXT_SLOT = re.compile(
    rf'jal (?P<open>{IDENT})\nmove (?P<input>\$s[0-7]), \$a0\n'
    rf'lui \$a0, %hi\((?P<base>{IDENT})\)\nlw \$a0, %lo\((?P=base)\)\(\$a0\)\n'
    rf'sw (?P=input), (?P<slot>{NUMBER})\(\$a0\)\nlw \$a1, (?P=slot)\(\$a0\)\n'
    rf'addiu \$v1, \$zero, (?P<flag>{NUMBER})\nsh \$v1, (?P<flag_off>{NUMBER})?\(\$a0\)\n'
    rf'lw \$v1, (?P<field>{NUMBER})\(\$a1\)\nsw \$v1, (?P<output>{NUMBER})\(\$a0\)\n'
    rf'jal (?P<close>{IDENT})\nmove \$a0, \$v0'
)


def _context_slot_reload(source, name, header, rows, changed):
    if not 1 <= len(changed) <= 8 or not 15 <= len(rows) <= 30 or 'M2C_FIELD' not in source:
        return None
    target = _CONTEXT_SLOT.search('\n'.join(row[1] for row in rows if row[1]))
    if not target or not any(rows[i][1].startswith('lw $a1, ') for i in changed):
        return None
    local, slot = '__repair_context', '__repair_context_slot'
    if local in source + header or not (part := view(source, name)):
        return None
    base = target['base']
    if (not re.search(rf'\bextern\s+void\s*\*\s*{base}\s*;', part.clean[:part.opening])
            or re.search(rf'\bvolatile\b[^;{{}}\n]*\b{base}\b', header + part.clean[:part.opening])):
        return None
    signature = re.search(rf'\bvoid\s+{re.escape(name)}\(void\s*\*\s*(?P<arg>{IDENT})\)\s*$',
                          part.clean[:part.opening])
    if not signature:
        return None
    draft = re.fullmatch(
        rf'\s*s32 (?P<saved>{IDENT});\s*void \*(?P<reload>{IDENT});\s*'
        rf'(?P=saved) = {target["open"]}\(\);\s*'
        rf'(?P<slot>M2C_FIELD\({base}, void \*\*, (?P<slot_off>{NUMBER})\)) = {signature["arg"]};\s*'
        rf'(?P=reload) = (?P=slot);\s*'
        rf'M2C_FIELD\({base}, s16 \*, (?P<flag_off>{NUMBER})\) = (?P<flag>{NUMBER});\s*'
        rf'M2C_FIELD\({base}, s32 \*, (?P<output>{NUMBER})\) = (?:\(s32\) )?'
        rf'M2C_FIELD\((?P=reload), s32 \*, (?P<field>{NUMBER})\);\s*'
        rf'{target["close"]}\((?P=saved), (?P=reload)\);\s*}}?\s*',
        part.body)
    if not draft or any(integer(draft[key]) != integer(target[key] or '0')
                        for key in ('flag_off', 'flag', 'output', 'field')):
        return None
    if integer(draft['slot_off']) != integer(target['slot']):
        return None
    saved, reload = draft['saved'], draft['reload']
    closing = part.clean.rfind('}', part.opening, part.end)
    replacement = (f'\n    void *{local};\n    void **{slot};\n    s32 {saved};\n    void *{reload};\n\n'
                   f'    {saved} = {target["open"]}();\n    {local} = {base};\n'
                   f'    {draft["slot"]} = {signature["arg"]};\n    {slot} = &{draft["slot"]};\n'
                   f'    M2C_FIELD({local}, s16 *, {draft["flag_off"]}) = {draft["flag"]};\n'
                   f'    {reload} = *{slot};\n'
                   f'    M2C_FIELD({local}, s32 *, {draft["output"]}) = (s32) '
                   f'M2C_FIELD({reload}, s32 *, {draft["field"]});\n'
                   f'    {target["close"]}({saved}, {reload});\n')
    return edit(source, [(part.opening + 1, closing, replacement)])


def variants(source, name, header, rows, asm, changed):
    if not asm:
        return []
    if candidate := _context_slot_reload(source, name, header, rows, changed):
        return [('stored_context_slot_reload', candidate)]
    if len(changed) == 5 and '__cosf' in source:
        if candidate := _indexed_cosine(source, name, header, rows, asm, changed):
            return [('narrow_index_and_float_call', candidate)]
    if len(changed) == 6 and 'M2C_FIELD' in source:
        if candidate := _callback_reset(source, name, header, rows, asm, changed):
            return [('callback_reset_pointer_reloads', candidate)]
    return []


def _normalized(asm):
    text = '\n'.join(' '.join(op.split()) for op in instructions(asm))
    return re.sub(r'(?<!\w)0x[\da-fA-F]+\b', lambda m: str(int(m[0], 16)), text)


def _indexed_cosine(source, name, header, rows, asm, changed):
    first = changed[0]
    if changed != [first, first + 1, first + 2, first + 4, first + 5]:
        return None
    if (not re.fullmatch(r'andi \$a0, \$a0, (?:0xffff|65535)', rows[first][1])
            or not re.fullmatch(r'andi \$a1, \$a0, (?:0xffff|65535)', rows[first][2])
            or any(rows[i][2] != rows[i][1].replace('$a0', '$a1') for i in changed[1:4])
            or (rows[changed[-1]][1], rows[changed[-1]][2]) != ('sll $v0, $v0, 2', 'sll $v0, $v0, 4')):
        return None
    target = _normalized(asm)
    indexed = _INDEX.search(target)
    if not indexed or not re.search(r'(?m)^jal __cosf\ncvt\.s\.d (\$(?:fa0|f12)), \1$', target):
        return None
    part = view(source, name)
    if not part or re.search(rf'\b{re.escape(name)}\s*\(', header):
        return None
    signature = re.search(rf'\bvoid\s+{re.escape(name)}\(\s*(?P<type>s32)\s+(?P<formal>{IDENT})\s*\)\s*$',
                          part.clean[:part.opening])
    if not signature:
        return None
    formal = signature['formal']
    symbol = indexed['symbol']
    mask = re.search(rf'(?m)^[ \t]*(?P<local>{IDENT})\s*=\s*{formal}\s*&\s*(?P<mask>{NUMBER});[ \t]*\n'
                     rf'\s*{IDENT}\s*=\s*\((?P<index>(?P=local))\s*\*\s*(?P<stride>{NUMBER})\)\s*\+\s*'
                     rf'(?P<address>&{symbol})\s*;', part.clean[part.opening + 1:part.end])
    if not mask or integer(mask['mask']) != 65535 or integer(mask['stride']) != 100:
        return None
    temporary = mask['local']
    declaration = re.search(rf'(?m)^[ \t]*s32\s+{temporary}\s*;[ \t]*\n', part.body[:mask.start()])
    site = list(calls(part, '__cosf'))
    if (not declaration or len(site) != 1 or len(re.findall(rf'\b{temporary}\b', part.body)) != 4
            or len(re.findall(rf'\b{formal}\b', part.body)) != 1):
        return None
    arg_start, arg_end = site[0]
    args = split_args(part.clean[arg_start:arg_end])
    if len(args) != 2 or part.clean[arg_start + args[1][0]:arg_end].strip() != temporary:
        return None
    prototype = re.search(r'(?m)^\s*f32\s+__cosf\(\s*f32(?P<extra>\s*,\s*s32)\s*\)\s*;',
                          part.clean[:part.opening])
    if not prototype:
        return None
    start = part.opening + 1
    assignment_end = part.body.index('\n', mask.end('mask')) + 1
    return edit(source, [(*signature.span('type'), 'u16'),
                         (start + declaration.start(), start + declaration.end(), ''),
                         (start + mask.start(), start + assignment_end, ''),
                         (start + mask.start('index'), start + mask.end('index'), formal),
                         (start + mask.start('address'), start + mask.start('address'), '(u8 *)'),
                         (*prototype.span('extra'), ''),
                         (arg_start + args[0][1], arg_end, '')])


def _callback_reset(source, name, header, rows, asm, changed):
    first = changed[0]
    if changed != [first, first + 1, first + 2, first + 3, first + 4, first + 12]:
        return None
    for at in changed:
        marker, target, actual = rows[at]
        replacement = ('$v1', '$v0') if at <= first + 2 else ('$a0', '$v1')
        if marker != 'r' or actual != target.replace(*replacement):
            return None
    reset = _CALLBACK_RESET.search(_normalized(asm))
    part = view(source, name) if reset else None
    if not part or '__repair_reset_' in source + header:
        return None
    base = reset['base']
    if not re.search(rf'\bextern\s+void\s*\*\s*{base}\s*;', part.clean[:part.opening]):
        return None
    pattern = re.compile(
        rf'(?m)^(?P<indent>[ \t]*)M2C_FIELD\({base}, s8 \*, (?P<first>{NUMBER})\) = 0;\s*'
        rf'M2C_FIELD\({base}, M2C_UNK \*\*, (?P<slot1>{NUMBER})\) = &{reset["handler1"]};\s*'
        rf'M2C_FIELD\({base}, M2C_UNK \*\*, (?P<slot2>{NUMBER})\) = &{reset["handler2"]};\s*'
        rf'M2C_FIELD\({base}, s8 \*, (?P<second>{NUMBER})\) = -1;\s*'
        rf'M2C_FIELD\({base}, s8 \*, (?P<last>{NUMBER})\) = 0;(?=\s*return 0;)')
    match = pattern.search(part.clean, part.opening + 1, part.end)
    offsets = ('first', 'slot1', 'slot2', 'second', 'last')
    if not match or any(integer(match[key]) != int(reset[key]) for key in offsets):
        return None
    indent = match['indent']
    first_base, second_base, invalid = ('__repair_reset_first', '__repair_reset_second', '__repair_reset_invalid')
    body = f"""
{indent}{invalid} = -1;
{indent}{first_base} = {base};
{indent}M2C_FIELD({first_base}, s8 *, {match['first']}) = 0;
{indent}{second_base} = {base};
{indent}M2C_FIELD({first_base}, M2C_UNK **, {match['slot1']}) = &{reset['handler1']};
{indent}M2C_FIELD({first_base}, M2C_UNK **, {match['slot2']}) = &{reset['handler2']};
{indent}M2C_FIELD({second_base}, s8 *, {match['second']}) = {invalid};
{indent}M2C_FIELD({base}, s8 *, {match['last']}) = 0;
"""
    declarations = f'\n    char *{first_base}, *{second_base};\n    int {invalid};'
    return edit(source, [(part.opening + 1, part.opening + 1, declarations),
                         (*match.span(), body.strip('\n'))])
