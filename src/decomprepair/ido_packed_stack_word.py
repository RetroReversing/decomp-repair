"""Restore IDO's byte-wise bitfield updates to one stack word."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import normalized_integer_lines
from .pattern_repairs import close
from .shared_default_drafts import _instructions

FAMILY = 'ido_packed_stack_word'
_TAIL = re.compile(
    r'lui \$a0, \((?P<addr>\d+) >> 16\)\nori \$a0, \$a0, \((?P=addr) & 65535\)\n'
    rf'jal (?P<call>{IDENT})\nlw \$a1, (?P<slot>\d+)\(\$sp\)\n'
    r'lui \$a0, \((?P<clear>\d+) >> 16\)\njal (?P=call)\nor \$a1, \$zero, \$zero\n'
    r'lw \$ra, \d+\(\$sp\)\naddiu \$sp, \$sp, (?P<frame>\d+)\njr \$ra\nnop$'
)


def _target(asm):
    if not asm or 'sb' not in asm or 'sra' not in asm or 'jal' not in asm:
        return None
    rows = normalized_integer_lines(_instructions(asm)[0])
    if len(rows) not in (33, 37):
        return None
    text = '\n'.join(rows)
    tail = _TAIL.search(text)
    if not tail:
        return None
    slot, frame = int(tail['slot']), int(tail['frame'])
    if slot % 4 or not 16 <= slot <= frame - 4 or not 0 <= int(tail['clear']) <= 0xFFFF0000 or int(tail['clear']) % 65536:
        return None
    init = f'sw $zero, {slot}($sp)'
    if rows[0] != f'addiu $sp, $sp, -{frame}' or rows.count(init) != 1:
        return None
    fields = 3 if len(rows) == 37 else 2
    prefix = rows[1:text[:tail.start()].count('\n')]
    if any(row.split()[0] not in ('sw', 'lw', 'lb', 'sb', 'sll', 'sra', 'andi', 'or', 'ori') for row in prefix):
        return None
    byte_access = re.findall(r'(?m)^(lb|sb) \$\w+, (\d+)\(\$sp\)$', text)
    expected = [(op, i) for op in ('lb', 'sb') for i in range(slot, slot + fields)]
    if sorted((op, int(offset)) for op, offset in byte_access) != expected:
        return None
    init_index = prefix.index(init)
    if any(init_index >= index
           for index, row in enumerate(prefix) if row.startswith(('lb ', 'sb '))):
        return None
    masks = [252, 65283, 31, 65504] + ([65287] if fields == 3 else [])
    if sorted(map(int, re.findall(r'(?m)^andi \$\w+, \$\w+, (\d+)$', text))) != sorted(masks):
        return None
    for shift in (26, 27):
        if any(len(re.findall(rf'(?m)^{op} \$\w+, \$\w+, {shift}$', text)) != 1 for op in ('sll', 'sra')):
            return None
    constant = re.search(r'(?m)^ori \$\w+, \$\w+, (\d+)$', text[:tail.start()])
    if (fields == 3 and (not constant or int(constant[1]) != 32)) or (fields == 2 and constant):
        return None
    return tail, fields


def applies(asm):
    return _target(asm) is not None


def rewrite(source, name, asm, header=''):
    if not source or 'unksp' not in source or '_m2c_packed_' in source + header or not (target := _target(asm)):
        return None
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return None
    sig = re.search(rf'\bvoid\s+{re.escape(name)}\(s32 (?P<x>{IDENT}), s32 (?P<y>{IDENT})\)\s*$',
                    part.clean[:part.opening])
    if not sig:
        return None
    tail, fields = target
    x, y = sig.groups()
    slot = int(tail['slot'])
    raw, low = f'sp{slot:X}', f'unksp{slot + 1:X}'
    third = f'unksp{slot + 2:X}'
    call = tail['call']
    extra = rf'{third} = \({third} & 0xFF07\) \| 0x20; ' if fields == 3 else ''
    draft = re.fullmatch(
        rf's32 {raw}; {raw} = 0; '
        rf'{raw} = \(\(\(\(s32\) \({x} << 0x1A\) >> 0x1A\) \* 4\) & 0xFC\) \| \(\(s8\) {raw} & 0xFF03\); '
        rf'{low} = \(\(\(s32\) \({y} << 0x1B\) >> 0x1B\) & 0x1F\) \| \({low} & 0xFFE0\); '
        + extra + rf'{call}\((?P<addr>{NUMBER}), \(s32\) {raw}\); {call}\((?P<clear>{NUMBER}), 0\);',
        ' '.join(part.clean[part.opening + 1:end - 1].split()))
    if not draft or any(integer(draft[key]) != int(tail[key]) for key in ('addr', 'clear')):
        return None
    if re.search(rf'\b(?:{low}|{third})\b', header):
        return None
    setting = '    _m2c_packed_word.bits.z = 4;\n' if fields == 3 else ''
    body = f'''
    union {{
        s32 value;
        struct {{ signed int x:6; unsigned int padding:5; signed int y:5; int z:5; }} bits;
    }} _m2c_packed_word;

    _m2c_packed_word.value = 0;
    _m2c_packed_word.bits.x = ({x} << 26) >> 26;
    _m2c_packed_word.bits.y = ({y} << 27) >> 27;
{setting}    {call}({draft['addr']}, _m2c_packed_word.value);
    {call}({draft['clear']}, 0);
'''
    return edit(source, [(part.opening + 1, end - 1, body)])
