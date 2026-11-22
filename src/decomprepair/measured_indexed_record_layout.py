"""Recover a measured indexed record layout from related address symbols."""

import re

from .integer_repair_support import edit, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines
from .pattern_repairs import close

_SOURCE = _shape('''
    s32 @offset; void *@seq; void *@player;
    @offset = @index * 0x184;
    @player = @offset + &@base;
    if (@check(@player) == 0) {
        @seq = @offset + (&@base + 0x7C);
        @load(@seq, *(&@data + @offset));
        @set(@player, @seq);
        @play(@player);
        return;
    }
    @stop(@player);
    *(&@flags + @offset) = *(&@flags + @offset) | 2;
''')


def _address(name):
    hit = re.fullmatch(r'D_([0-9A-Fa-f]{8})', name)
    return int(hit[1], 16) if hit else None


def variants(source, name, header, rows):
    if not 35 <= len(rows) <= 65:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    candidate = '\n'.join(normalized_integer_lines(right for _, _, right in rows if right))
    if ('sll $s1, $v0, 2' not in target or 'addiu $s0, $s0, 124' not in target
            or 'sll $s1, $v0, 4' not in candidate):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end or (re.search(r'\b(?:volatile|asm|__asm__|__LINE__|__repair_record)\b', part.clean)
                   or re.search(r'\b__repair_record\b', header)):
        return []
    part.end = end
    draft = _SOURCE.fullmatch(' '.join(part.body.split()))
    if not draft or not re.search(rf'\bvoid\s+{re.escape(name)}\s*\(\s*s32\s+{re.escape(draft["index"])}\s*\)\s*$',
                                  part.clean[:part.opening]):
        return []
    base, data, flags = (_address(draft[k]) for k in ('base', 'data', 'flags'))
    if base is None or data != base + 0x174 or flags != base + 0x17C:
        return []
    if any(re.search(rf'\b{re.escape(draft[k])}\b', header) for k in ('base', 'data', 'flags')):
        return []
    for key in ('base', 'data', 'flags'):
        symbol = re.escape(draft[key])
        if f'%hi({draft[key]})' not in target or not re.search(rf'\bextern\s+M2C_UNK\s+{symbol}\s*;',
                                                                part.clean[:part.opening]):
            return []
    for key in ('check', 'load', 'set', 'play', 'stop'):
        if f'jal {draft[key]}' not in target:
            return []
    original = source[part.opening + 1:part.end - 1]
    if '/*' in original or '//' in original or '#' in original:
        return []
    declaration = re.search(rf'\bextern\s+M2C_UNK\s+{re.escape(draft["base"])}\s*;', part.clean[:part.opening])
    if source[declaration.start():declaration.end()] != declaration[0]:
        return []
    layout = ('typedef struct { u8 player[0x7C]; u8 seq[0xF8]; s32 data; '
              's32 pad178; s32 flags; s32 pad180; } __repair_record;\n'
              f'extern __repair_record {draft["base"]}[];')
    record = f'{draft["base"]}[{draft["index"]}]'
    body = (f'\n    if ({draft["check"]}({record}.player) == 0) {{\n'
            f'        {draft["load"]}({record}.seq, {record}.data);\n'
            f'        {draft["set"]}({record}.player, {record}.seq);\n'
            f'        {draft["play"]}({record}.player);\n'
            f'    }} else {{\n        {draft["stop"]}({record}.player);\n'
            f'        {record}.flags |= 2;\n    }}\n')
    fixed = edit(source, [(declaration.start(), declaration.end(), layout),
                          (part.opening + 1, part.end - 1, body)])
    return [('measured_indexed_record_layout', fixed)]
