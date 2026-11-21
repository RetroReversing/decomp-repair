"""Recover row indexing and packed word cursors for a measured KMC conversion."""

import re

from .integer_repair_support import IDENT, edit, view
from .large_stack_drafts import _shape
from .measured_stack_drafts import _lines

FREG = r'\$f\w+'
LABEL = r'\.L\w+'
HIGH_MASK = r'(?:\(0xFFFF0000 >> 16\)|0xFFFF)'
SCALE = r'(?:\(0x47800000 >> 16\)|0x4780)'
ZERO = r'(?:0x0|0)?'
TARGET = re.compile(
    rf'(?m)^move \$t0, \$a1\naddiu \$t1, \$t0, (?:0x20|32)\nmove \$t3, \$zero\n'
    rf'lui \$at, {SCALE}\nmtc1 \$at, (?P<scale>{FREG})\nlui \$t4, {HIGH_MASK}\nmove \$t2, \$a0\n'
    rf'(?P<outer>{LABEL}):\nmove \$a3, \$zero\nmove \$a2, \$t2\n(?P<inner>{LABEL}):\n'
    rf'lwc1 (?P<first>{FREG}), {ZERO}\(\$a2\)\nmul.s (?P=first), (?P=first), (?P=scale)\n'
    rf'lwc1 (?P<second>{FREG}), (?:0x4|4)\(\$a2\)\nmul.s (?P=second), (?P=second), (?P=scale)\n'
    r'addiu \$a2, \$a2, (?:0x8|8)\naddiu \$a3, \$a3, (?:0x1|1)\n'
    rf'trunc.w.s (?P<trunc>{FREG}), (?P=first)\nmfc1 \$a0, (?P=trunc)\n'
    r'trunc.w.s (?P=first), (?P=second)\nmfc1 \$a1, (?P=first)\n'
    r'and \$v0, \$a0, \$t4\nsrl \$v1, \$a1, (?:0x10|16)\nor \$v0, \$v0, \$v1\n'
    rf'sw \$v0, {ZERO}\(\$t0\)\naddiu \$t0, \$t0, (?:0x4|4)\nsll \$a0, \$a0, (?:0x10|16)\n'
    r'and \$a0, \$a0, \$t4\nandi \$a1, \$a1, 0xFFFF\nor \$a0, \$a0, \$a1\n'
    rf'sw \$a0, {ZERO}\(\$t1\)\nslti \$v0, \$a3, (?:0x2|2)\nbnez \$v0, (?P=inner)\n'
    r'addiu \$t1, \$t1, (?:0x4|4)\naddiu \$t3, \$t3, (?:0x1|1)\n'
    r'slti \$v0, \$t3, (?:0x4|4)\nbnez \$v0, (?P=outer)\n'
    r'addiu \$t2, \$t2, (?:0x10|16)\njr \$ra\nnop$',
    re.I,
)

DRAFT = '''
    f32 @second;
    f32 @first;
    {pointer} *@integer;
    {pointer} *@fraction;
    s32 @fixfirst;
    s32 @fixsecond;
    s32 @pair;
    s32 @row;
    void *@cursor;
    void *@rowbase;

    @integer = @dest;
    @fraction = @integer + 0x20;
    {initialize}
    do {{
        @pair = 0;
        @cursor = @rowbase;
    @label:
        @first = M2C_FIELD(@cursor, f32 *, 0) * 65536.0f;
        @second = M2C_FIELD(@cursor, f32 *, 4) * 65536.0f;
        @cursor += 8;
        @pair += 1;
        @fixfirst = (s32) @first;
        @fixsecond = (s32) @second;
        {store}@integer = (@fixfirst & 0xFFFF0000) | ((u32) @fixsecond >> 0x10);
        @integer += 4;
        {store}@fraction = ((@fixfirst << 0x10) & 0xFFFF0000) | (@fixsecond & 0xFFFF);
        @fraction += 4;
        if (@pair < 2) {{
            goto @label;
        }}
        @row += 1;
        @rowbase += 0x10;
    }} while (@row < 4);
'''
DRAFTS = tuple(
    _shape(DRAFT.format(pointer=pointer, store=store, initialize=initialize))
    for pointer, store in (('s32', '*'), ('char', '*(s32 *)'))
    for initialize in ('@row = 0; @rowbase = @input;', '@rowbase = @input; @row = 0;')
)


def applies(asm):
    if 'trunc.w.s' not in asm or 'mul.s' not in asm:
        return False
    lines = '\n'.join(' '.join(line.split()) for line in _lines(asm)
                      if not line.startswith(('glabel ', 'endlabel ')))
    lines = re.sub(r'(?m)^addu (\$\w+), (\$\w+), \$zero$', r'move \1, \2', lines)
    return TARGET.fullmatch(lines) is not None


def rewrite(source, name, asm, header=''):
    """Recover a typed 4x4 input and the two word streams in store order."""
    if '65536.0f' not in source or '__repair_matrix_' in source + header or not applies(asm):
        return None
    part = view(source, name)
    if not part:
        return None
    signature = re.search(
        rf'\bvoid\s+{re.escape(name)}\(void \*(?P<input>{IDENT}), s32 \*(?P<dest>{IDENT})\)\s*$',
        part.clean[:part.opening])
    if not signature:
        return None
    start = part.opening + 1
    end = part.clean.rfind('}', start, part.end)
    text = ' '.join(part.clean[start:end].split())
    draft = next((hit for pattern in DRAFTS if (hit := pattern.fullmatch(text))), None)
    if (not draft or draft['input'] != signature['input'] or draft['dest'] != signature['dest']
            or len(set(draft.groups())) != len(draft.groups())):
        return None

    body = f'''
    float (*__repair_matrix_rows)[4] = (float (*)[4]){draft['input']};
    int __repair_matrix_row, __repair_matrix_pair;
    int __repair_matrix_first, __repair_matrix_second;
    int *__repair_matrix_integer, *__repair_matrix_fraction;

    __repair_matrix_integer = (int *){draft['dest']};
    __repair_matrix_fraction = (int *)((u8 *){draft['dest']} + 0x20);

    for (__repair_matrix_row = 0; __repair_matrix_row < 4; __repair_matrix_row++)
    for (__repair_matrix_pair = 0; __repair_matrix_pair < 2; __repair_matrix_pair++) {{
        __repair_matrix_first = (long)(__repair_matrix_rows[__repair_matrix_row][__repair_matrix_pair * 2] * (float)0x10000);
        __repair_matrix_second = (long)(__repair_matrix_rows[__repair_matrix_row][__repair_matrix_pair * 2 + 1] * (float)0x10000);
        *(__repair_matrix_integer++) = (__repair_matrix_first & 0xffff0000) | ((u32)__repair_matrix_second >> 16);
        *(__repair_matrix_fraction++) = (((u32)__repair_matrix_first << 16) & 0xffff0000) | (__repair_matrix_second & 0xffff);
    }}
'''
    return edit(source, [(start, end, body)])
