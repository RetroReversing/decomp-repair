"""Recover a contiguous stack array and measured call-argument scheduling."""

import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, integer, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines
from .pattern_repairs import close

_STACK_TARGET = re.compile(
    rf'addiu \$sp, \$sp, -48\nsw \$s2, 40\(\$sp\)\nmove \$s2, \$a0\n'
    r'sw \$s1, 36\(\$sp\)\nmove \$s1, \$zero\nsw \$s0, 32\(\$sp\)\n'
    r'addiu \$s0, \$zero, 16\nsw \$ra, 44\(\$sp\)\n'
    r'sw \$zero, 16\(\$sp\)\nsw \$zero, 20\(\$sp\)\nsw \$zero, 24\(\$sp\)\n'
    r'lw \$a1, (?P<field>\d+)\(\$s2\)\naddiu \$s1, \$s1, 1\nmove \$a0, \$s2\n'
    rf'addiu \$a2, \$sp, 16\njal (?P<call>{IDENT})\naddu \$a1, \$a1, \$s0\n'
    r'sltiu \$v0, \$s1, 12\nbnez \$v0, 44\naddiu \$s0, \$s0, 20\n'
    r'lw \$ra, 44\(\$sp\)\nlw \$s2, 40\(\$sp\)\nlw \$s1, 36\(\$sp\)\n'
    r'lw \$s0, 32\(\$sp\)\njr \$ra\naddiu \$sp, \$sp, 48'
)
_STACK_SOURCE = _shape('''
    s32 @first; s32 @second; s32 @third; s32 @offset; u32 @index;
    @index = 0; @offset = 0x10; @first = 0; @second = 0; @third = 0;
    do { @index += 1; @call(@arg, M2C_FIELD(@arg, s32 *, @field) + @offset, &@first); @offset += 0x14; }
    while (@index < 0xCU);
''', numbers=('field',))
_CALL_TARGET = re.compile(
    rf'lui \$v0, %hi\((?P<guard>{IDENT})\)\nlw \$v0, %lo\((?P=guard)\)\(\$v0\)\n'
    r'addiu \$sp, \$sp, -32\nmove \$v1, \$a0\nbeqz \$v0, 56\nsw \$ra, 24\(\$sp\)\n'
    rf'lbu \$v0, (?P<fifth>\d+)\(\$v1\)\nlui \$a0, %hi\((?P<first>{IDENT})\)\n'
    r'lw \$a0, %lo\((?P=first)\)\(\$a0\)\nlbu \$a1, (?P<second>\d+)\(\$v1\)\n'
    r'lbu \$a2, (?P<third>\d+)\(\$v1\)\nlbu \$a3, (?P<fourth>\d+)\(\$v1\)\n'
    rf'jal (?P<call>{IDENT})\nsw \$v0, 16\(\$sp\)\nlw \$ra, 24\(\$sp\)\n'
    r'jr \$ra\naddiu \$sp, \$sp, 32'
)
_CALL_SOURCE = _shape('''
    if (M2C_FIELD(&@owner, s32 *, @guardoff) != 0) {
        @call(M2C_FIELD(&@other, s32 *, @firstoff),
        M2C_FIELD(@arg, u8 *, @second), M2C_FIELD(@arg, u8 *, @third),
        M2C_FIELD(@arg, u8 *, @fourth), (s32) M2C_FIELD(@arg, u8 *, @fifth));
    }
''', numbers=('guardoff', 'firstoff', 'second', 'third', 'fourth', 'fifth'))


def variants(source, name, header, rows, resolve=None):
    if len(rows) not in (19, 26):
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    changes = [normalized_integer_lines((left, right)) for tag, left, right in rows if tag != ' ']
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    body = ' '.join(part.body.split())
    if (hit := _STACK_TARGET.fullmatch(target)):
        draft = _STACK_SOURCE.fullmatch(body)
        if not draft or ('sw $zero, 16($sp)', '') not in changes:
            return []
        fixed = _stack(part, name, header, draft, hit)
        family = 'measured_three_word_stack_array'
    elif resolve and (hit := _CALL_TARGET.fullmatch(target)):
        draft = _CALL_SOURCE.fullmatch(body)
        if not draft or ('move $v1, $a0', '') not in changes:
            return []
        fixed = _call(part, name, header, draft, hit, resolve)
        family = 'measured_staged_guarded_color_call'
    else:
        return []
    return [(family, fixed)] if fixed else []


def _stack(part, name, header, draft, target):
    array = '__repair_words'
    names = [draft[key] for key in ('first', 'second', 'third')]
    try:
        offsets = [int(item[2:], 16) for item in names]
    except ValueError:
        return None
    if (offsets != [16, 20, 24] or names != [f'sp{offset:X}' for offset in offsets]
            or draft['call'] != target['call'] or integer(draft['field']) != int(target['field'])
            or array in part.clean + _blank(header)
            or not re.search(rf'\bvoid {re.escape(name)}\(void \*{draft["arg"]}\)\s*$', part.clean[:part.opening])):
        return None
    source = part.source
    body = source[part.opening + 1:part.end - 1]
    declarations = re.compile(r'\bs32 sp10;\s*s32 sp14;\s*s32 sp18;')
    body, count = declarations.subn(f's32 {array}[3];', body)
    if count != 1:
        return None
    for i, old in enumerate(names):
        body = re.sub(rf'&{old}\b', array, body)
        body = re.sub(rf'\b{old}\b', f'{array}[{i}]', body)
    return edit(source, [(part.opening + 1, part.end - 1, body)])


def _call(part, name, header, draft, target, resolve):
    arg, call = draft['arg'], draft['call']
    if (call != target['call'] or not re.search(rf'\bvoid {re.escape(name)}\(void \*{arg}\)\s*$', part.clean[:part.opening])
            or any(integer(draft[key]) != int(target[key]) for key in ('second', 'third', 'fourth', 'fifth'))):
        return None
    for base, offset, symbol in (('owner', 'guardoff', 'guard'), ('other', 'firstoff', 'first')):
        value = resolve(draft[base])
        if value is None or value + integer(draft[offset]) != resolve(target[symbol]):
            return None
    obj, first = '__repair_call_base', '__repair_call_first'
    if obj in part.clean + _blank(header) or first in part.clean + _blank(header):
        return None
    fixed = f'''
    void *{obj};
    s32 {first};
    {obj} = {arg};
    if (M2C_FIELD(&{draft["owner"]}, s32 *, {draft["guardoff"]}) != 0) {{
        {first} = M2C_FIELD(&{draft["other"]}, s32 *, {draft["firstoff"]});
        {call}({first}, M2C_FIELD({obj}, u8 *, {draft["second"]}),
             M2C_FIELD({obj}, u8 *, {draft["third"]}), M2C_FIELD({obj}, u8 *, {draft["fourth"]}),
             (s32) M2C_FIELD({obj}, u8 *, {draft["fifth"]}));
    }}
'''
    return edit(part.source, [(part.opening + 1, part.end - 1, fixed)])
