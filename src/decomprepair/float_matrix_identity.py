"""Recover the floating diagonal and word-scaled cursors of a KMC matrix loop."""

import re

from .integer_repair_support import IDENT, edit, view
from .large_stack_drafts import _shape
from .measured_stack_drafts import _lines

LABEL = r'\.L\w+'
ZERO = r'(?:0x0|0)?'
TARGET = re.compile(
    r'move \$a2, \$zero\nlui \$at, (?:\(0x3F800000 >> 16\)|0x3F80|16256)\n'
    r'mtc1 \$at, (?P<one>\$f\w+)\nmove \$a3, \$a0\n'
    rf'(?P<row>{LABEL}):\nmove \$v1, \$zero\nmove \$a1, \$a0\n(?P<col>{LABEL}):\n'
    rf'bnel \$a2, \$v1, (?P<advance>{LABEL})\nsw \$zero, {ZERO}\(\$a1\)\n'
    rf'swc1 (?P=one), {ZERO}\(\$a3\)\n(?P=advance):\n'
    r'addiu \$v1, \$v1, (?:0x1|1)\nslti \$v0, \$v1, (?:0x4|4)\nbnez \$v0, (?P=col)\n'
    r'addiu \$a1, \$a1, (?:0x4|4)\naddiu \$a3, \$a3, (?:0x14|20)\n'
    r'addiu \$a2, \$a2, (?:0x1|1)\nslti \$v0, \$a2, (?:0x4|4)\nbnez \$v0, (?P=row)\n'
    r'addiu \$a0, \$a0, (?:0x10|16)\njr \$ra\nnop',
    re.I,
)

SOURCE = '''
    M2C_UNK32 *@base;
    M2C_UNK32 *@cursor;
    M2C_UNK32 *@diag;
    s32 @row;
    s32 @col;

    @base = @arg;
    {initialize}
    do {{
        @col = 0;
        @cursor = @base;
    @inner:
        {branch}
        @col += 1;
        @cursor += 4;
        if (@col < 4) {{
            goto @inner;
        }}
        @diag += 0x14;
        @row += 1;
        @base += 0x10;
    }} while (@row < 4);
'''
DRAFTS = tuple(
    _shape(SOURCE.format(initialize=initialize, branch=branch))
    for initialize in ('@row = 0; @diag = @base;', '@diag = @base; @row = 0;')
    for branch in (
        'if (@row != @col) { *@cursor = 0; } else { *@diag = 0x3F800000; }',
        'if (@row == @col) { *@diag = 0x3F800000; } else { *@cursor = 0; }',
    )
)


def applies(asm):
    if 'swc1' not in asm or 'bnel' not in asm:
        return False
    lines = '\n'.join(' '.join(line.split()) for line in _lines(asm)
                      if not line.startswith(('glabel ', 'endlabel ')))
    lines = re.sub(r'(?m)^addu (\$\w+), (\$\w+), \$zero$', r'move \1, \2', lines)
    target = TARGET.fullmatch(lines)
    return bool(target and len({target[key] for key in ('row', 'col', 'advance')}) == 3)


def rewrite(source, name, asm, header=''):
    """Restore the 4×4 traversal while keeping the measured initialization order."""
    one = '__repair_matrix_one'
    if '0x3F800000' not in source or one in source + header or not applies(asm):
        return None
    part = view(source, name)
    if not part:
        return None
    signature = re.search(rf'\bvoid\s+{re.escape(name)}\s*\(\s*M2C_UNK32\s*\*\s*({IDENT})\s*\)\s*$',
                          part.clean[:part.opening])
    start = part.opening + 1
    end = part.clean.rfind('}', start, part.end)
    body = ' '.join(part.clean[start:end].split())
    draft = next((match for pattern in DRAFTS if (match := pattern.fullmatch(body))), None)
    if not signature or not draft or draft['arg'] != signature[1] or len(set(draft.groups())) != len(draft.groups()):
        return None

    arg, cursor, diag, row, col = (draft[key] for key in ('arg', 'cursor', 'diag', 'row', 'col'))
    return edit(source, [(start, end, f'''
    M2C_UNK32 *{cursor};
    M2C_UNK32 *{diag};
    s32 {row};
    s32 {col};
    f32 {one};

    {row} = 0;
    {one} = 1.0f;
    {diag} = {arg};
    do {{
        {col} = 0;
        {cursor} = {arg};
        do {{
            if ({row} == {col}) {{
                *(f32 *){diag} = {one};
            }} else {{
                *{cursor} = 0;
            }}
            {col}++;
            {cursor}++;
        }} while ({col} < 4);
        {diag} += 5;
        {row}++;
        {arg} += 4;
    }} while ({row} < 4);
''')])
