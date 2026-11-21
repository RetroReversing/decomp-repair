"""Recover one stack buffer behind a byte fill and a call."""

import re

from .integer_repair_support import IDENT, edit, view
from .large_stack_drafts import _shape
from .measured_stack_drafts import _lines
from .stack_read_retry import _decimal

TARGET = re.compile(
    r'addiu \$sp, \$sp, -(?P<frame>\d+)\nsw \$s0, (?P<save0>\d+)\(\$sp\)\n'
    r'move \$s0, \$a0\nsw \$s1, (?P<save1>\d+)\(\$sp\)\nmove \$s1, \$a1\n'
    r'addiu \$v1, \$zero, (?P<count>\d+)\naddiu \$v0, \$sp, (?P<end>\d+)\n'
    r'sw \$ra, (?P<ret>\d+)\(\$sp\)\n(?P<loop>\.L\w+):\n'
    r'sb \$s1, 0\(\$v0\)\naddiu \$v1, \$v1, -1\nbgez \$v1, (?P=loop)\naddiu \$v0, \$v0, -1\n'
    r'sw \$zero, 16\(\$sp\)\nlw \$a0, (?P<handle>\d+)\(\$s0\)\nlw \$a1, (?P<channel>\d+)\(\$s0\)\n'
    rf'addiu \$a2, \$zero, (?P<page>\d+)\njal (?P<write>{IDENT})\naddiu \$a3, \$sp, (?P<buffer>\d+)\n'
    r'beql \$v0, \$zero, (?P<exit>\.L\w+)\nsb \$s1, (?P<flag>\d+)\(\$s0\)\n(?P=exit):\n'
    r'lw \$ra, (?P=ret)\(\$sp\)\nlw \$s1, (?P=save1)\(\$sp\)\nlw \$s0, (?P=save0)\(\$sp\)\n'
    r'jr \$ra\naddiu \$sp, \$sp, (?P=frame)',
)


def _evidence(asm):
    if 'bgez' not in asm or 'sb' not in asm or 'jal' not in asm:
        return None
    lines = '\n'.join(' '.join(line.split()) for line in _lines(asm)
                      if not line.startswith(('glabel ', 'endlabel ')))
    lines = re.sub(r'(?m)^addu (\$\w+), (\$\w+), \$zero$', r'move \1, \2', lines)
    target = TARGET.fullmatch(_decimal(lines.replace('sb $s1, ($v0)', 'sb $s1, 0($v0)')))
    if not target or target['loop'] == target['exit']:
        return None
    buffer, count, end, save0, save1, ret, frame = (
        int(target[key]) for key in ('buffer', 'count', 'end', 'save0', 'save1', 'ret', 'frame'))
    if (buffer < 24 or buffer % 4 or not 4 <= count + 1 <= 64 or (count + 1) % 4
            or end != buffer + count or (save0, save1, ret) != (end + 1, end + 5, end + 9)
            or ret + 4 > frame or frame % 8):
        return None
    return target


def applies(asm):
    return _evidence(asm) is not None


def rewrite(source, name, asm, header=''):
    """Restore the array using the span between the call buffer and the first saved register."""
    local = '__repair_fill_buffer'
    if 'M2C_FIELD' not in source or local in source + header or not (target := _evidence(asm)):
        return None
    part = view(source, name)
    if not part:
        return None
    signature = re.search(
        rf'\bvoid\s+{re.escape(name)}\s*\(\s*void\s*\*\s*(?P<arg>{IDENT}),\s*s8\s+(?P<byte>{IDENT})\s*\)\s*$',
        part.clean[:part.opening])
    if not signature:
        return None
    arg, byte = signature['arg'], signature['byte']
    handle, channel, page, count, flag, write = (target[key] for key in ('handle', 'channel', 'page', 'count', 'flag', 'write'))
    args = f'M2C_FIELD({arg}, s32 *, {handle}), M2C_FIELD({arg}, s32 *, {channel}), {page}'
    check = f'M2C_FIELD({arg}, s8 *, {flag})'
    expected = _shape(f'''
        M2C_UNK @head;
        s8 @tail;
        s32 @count;
        s8 *@cursor;
        @count = {count};
        @cursor = &@tail;
        do {{
            *@cursor = {byte};
            @count -= 1;
            @cursor -= 1;
        }} while (@count >= 0);
        if ({write}({args}, &@head, 0) == 0) {{
            {check} = {byte};
        }}
    ''')
    start = part.opening + 1
    end = part.clean.rfind('}', start, part.end)
    draft = expected.fullmatch(' '.join(_decimal(part.clean[start:end]).split()))
    if not draft or len(set(draft.groups()) | {arg, byte}) != len(draft.groups()) + 2:
        return None
    counter = draft['count']
    return edit(source, [(start, end, f'''
    s32 {local}[{(int(count) + 1) // 4}];
    s32 {counter};

    {counter} = {count};
    do {{
        ((s8 *){local})[{counter}] = {byte};
        {counter} -= 1;
    }} while ({counter} >= 0);
    if ({write}({args}, (M2C_UNK *){local}, 0) == 0) {{
        {check} = {byte};
    }}
''')])


ASCENDING = re.compile(
    r'addiu \$sp, \$sp, -(?P<frame>\d+)\nsw \$ra, (?P<save>\d+)\(\$sp\)\nmove \$a1, \$a0\n'
    r'addiu \$v1, \$sp, (?P<start>\d+)\naddiu \$a0, \$sp, (?P=save)\n(?P<loop>\.L\w+):\n'
    r'lbu \$v0, (?P<value>\d+)\(\$a1\)\nsb \$v0, (?:0)?\(\$v1\)\naddiu \$v1, \$v1, 1\n'
    r'slt \$v0, \$v1, \$a0\nbnez \$v0, (?P=loop)\naddiu \$a2, \$zero, (?P<page>\d+)\n'
    r'sw \$zero, 16\(\$sp\)\nlw \$a0, (?P<handle>\d+)\(\$a1\)\nlw \$a1, (?P<channel>\d+)\(\$a1\)\n'
    rf'jal (?P<write>{IDENT})\naddiu \$a3, \$sp, (?P=start)\nlw \$ra, (?P=save)\(\$sp\)\n'
    r'jr \$ra\naddiu \$sp, \$sp, (?P=frame)',
)


def _ascending(asm):
    if 'lbu' not in asm or 'slt' not in asm or 'jal' not in asm:
        return None
    text = '\n'.join(' '.join(line.split()) for line in _lines(asm)
                     if not line.startswith(('glabel ', 'endlabel ')))
    text = re.sub(r'(?m)^addu (\$\w+), (\$\w+), \$zero$', r'move \1, \2', text)
    target = ASCENDING.fullmatch(_decimal(text))
    if target:
        start, save, frame = (int(target[key]) for key in ('start', 'save', 'frame'))
        if 24 <= start < save and start % 4 == 0 and 4 <= save - start <= 64 and save + 4 <= frame:
            return target
    return None


def ascending_applies(asm):
    return _ascending(asm) is not None


def rewrite_ascending(source, name, asm, header=''):
    """Fill one byte array up to the exclusive end shown by the original stack addresses."""
    local = '__repair_fill_buffer'
    index = '__repair_fill_index'
    if 'M2C_FIELD' not in source or any(token in source + header for token in (local, index)):
        return None
    if not (target := _ascending(asm)) or not (part := view(source, name)):
        return None
    signature = re.search(rf'\bvoid\s+{re.escape(name)}\s*\(\s*void\s*\*\s*(?P<arg>{IDENT})\s*\)\s*$',
                          part.clean[:part.opening])
    if not signature:
        return None
    arg = signature['arg']
    handle, channel, page, value, write = (target[key] for key in ('handle', 'channel', 'page', 'value', 'write'))
    args = f'M2C_FIELD({arg}, s32 *, {handle}), M2C_FIELD({arg}, s32 *, {channel}), {page}'
    field = f'M2C_FIELD({arg}, u8 *, {value})'
    first = f'sp{int(target["start"]):X}'
    last = f'unksp{int(target["save"]):X}'
    extent = int(target['save']) - int(target['start'])

    start = part.opening + 1
    end = part.clean.rfind('}', start, part.end)
    body = ' '.join(_decimal(part.clean[start:end]).split())
    for declaration, lower, upper in (
        (f'u8 {first};', f'&{first}', f'&{last}'),
        (f' union {{ unsigned char bytes[{int(target["frame"])}]; '
         f'struct {{ unsigned char pad[{target["start"]}]; u8 value; }} view_{first}; '
         f'struct {{ unsigned char pad[{target["save"]}]; s32 value; }} view_{last}; }} m2c_initial_frame;',
         f'&m2c_initial_frame.view_{first}.value', f'&m2c_initial_frame.view_{last}.value'),
    ):
        shape = _shape(f'''
            {declaration}
            u8 *@cursor;
            @cursor = {lower};
            do {{
                *@cursor = {field};
                @cursor += 1;
            }} while ((s32) @cursor < (s32) {upper});
            {write}({args}, {lower}, 0);
        ''')
        if (draft := shape.fullmatch(body)) and draft['cursor'] != arg:
            break
    else:
        return None

    return edit(source, [(start, end, f'''
    u8 {local}[{extent}];
    s32 {index};

    {index} = 0;
    do {{
        {local}[{index}] = {field};
        {index} += 1;
    }} while ({index} < {extent});
    {write}({args}, {local}, 0);
''')])
