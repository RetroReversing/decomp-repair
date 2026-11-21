"""Restore measured IDO loop cursors whose draft steps are expressed in bytes."""

import re

from .integer_repair_support import edit, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines
from .shared_default_drafts import _instructions

_HALFWORDS = _shape('''
    s32 @count; void *@cursor; @cursor = @base; @count = 0;
    do { @count += 4;
    M2C_FIELD(@cursor, s16 *, 2) = 0; M2C_FIELD(@cursor, s16 *, 4) = 0; M2C_FIELD(@cursor, s16 *, 6) = 0;
    @cursor += 8; M2C_FIELD(@cursor, s16 *, -8) = 0; } while (@count != 8);
''')
_WORDS = _shape('''
    s32 @count; void *@cursor;
    M2C_FIELD(@base, s8 *, 0x99) = 1; M2C_FIELD(@base, s32 *, 0x38) = 0; M2C_FIELD(@base, s32 *, 0x3C) = 0;
    @cursor = @base + 8; @count = 2;
    do { @count += 4; M2C_FIELD(@cursor, s32 *, 0x38) = 0; M2C_FIELD(@cursor, s32 *, 0x3C) = 0;
    M2C_FIELD(@cursor, s32 *, 0x40) = 0; M2C_FIELD(@cursor, s32 *, 0x44) = 0;
    @cursor += 0x10; } while (@count != 0xE);
''')
_MATRIX = _shape('''
    f32 *@from; f32 *@fromrow; f32 @value; s32 @row; s32 @column; void *@to; void *@torow;
    @row = 0; @torow = @destination; @fromrow = @source;
    do { @column = 0; @to = @torow; @from = @fromrow;
    @loop: @value = *@from; @column += 1; @to += 4; @from += 4; M2C_FIELD(@to, f32 *, -4) = @value;
    if (@column != 3) { goto @loop; }
    @row += 1; @torow += 0x10; @fromrow += 0x10; } while (@row != 3);
''')
_SHAPES = {
    '''move $v1, $a0
addiu $a0, $zero, 8
move $v0, $zero
addiu $v0, $v0, 4
sh $zero, 2($v1)
sh $zero, 4($v1)
sh $zero, 6($v1)
addiu $v1, $v1, 8
bne $v0, $a0, @3
sh $zero, -8($v1)
jr $ra
nop''': (_HALFWORDS, 'ido_unrolled_halfword_clear'),
    '''addiu $t6, $zero, 1
sb $t6, 153($a0)
sw $zero, 56($a0)
sw $zero, 60($a0)
addiu $v1, $a0, 8
addiu $a0, $zero, 14
addiu $v0, $zero, 2
addiu $v0, $v0, 4
sw $zero, 56($v1)
sw $zero, 60($v1)
sw $zero, 64($v1)
sw $zero, 68($v1)
bne $v0, $a0, @7
addiu $v1, $v1, 16
jr $ra
nop''': (_WORDS, 'ido_unrolled_word_clear'),
    '''move $v0, $zero
move $a2, $a1
move $a3, $a0
addiu $t0, $zero, 3
move $v1, $zero
move $a0, $a2
move $a1, $a3
lwc1 $ft0, 0($a1)
addiu $v1, $v1, 1
addiu $a0, $a0, 4
addiu $a1, $a1, 4
bne $v1, $t0, @7
swc1 $ft0, -4($a0)
addiu $v0, $v0, 1
addiu $a2, $a2, 16
bne $v0, $t0, @4
addiu $a3, $a3, 16
jr $ra
nop''': (_MATRIX, 'ido_strided_float_copy'),
}


def _target(asm):
    if 'bne' not in asm or not any(op in asm for op in ('sh ', 'sw ', 'swc1')):
        return None
    lines, labels = _instructions(asm)
    if len(lines) not in (12, 16, 19):
        return None
    result = []
    for line in normalized_integer_lines(lines):
        if line.startswith('bne '):
            operation, _, label = line.rpartition(', ')
            if label not in labels:
                return None
            line = f'{operation}, @{labels[label]}'
        line = re.sub(r'^(?:or|addu) (\$\w+), (\$\w+), \$zero$', r'move \1, \2', line)
        result.append(line.replace('$f4', '$ft0'))
    return _SHAPES.get('\n'.join(result))


def applies(asm):
    return _target(asm) is not None


def rewrite(source, name, asm, header=''):
    if ('M2C_FIELD(' not in source or not (target := _target(asm))
            or '__m2c_step_' in source + header):
        return []
    part = view(source, name)
    if not part:
        return []
    end = part.clean.rfind('}', part.opening, part.end)
    shape, family = target
    if shape is not _WORDS and re.search(rf'\b{re.escape(name)}\s*\(', header):
        return []
    match = shape.fullmatch(' '.join(part.clean[part.opening+1:end].split()))
    if not match or len(set(match.groupdict().values())) != len(match.groupdict()):
        return []
    if shape is _MATRIX:
        params = f'f32 *{match["source"]}, void *{match["destination"]}'
    else:
        params = f'void *{match["base"]}'
    signature = re.search(rf'\bvoid\s+{re.escape(name)}\({re.escape(params)}\)\s*$', part.clean[:part.opening])
    if not signature:
        return []

    result = _matrix(name, match) if shape is _MATRIX else _clear(name, match, shape is _HALFWORDS)
    return [(family, edit(source, [(signature.start(), end+1, result)]))]


def _matrix(name, roles):
    src, dst, row, col = (roles[key] for key in ('source', 'destination', 'row', 'column'))
    # IDO's original carrier registers depend on initializing the column counter
    # and staging the destination row before the source row.
    return f'''void {name}(float *{src}, float *{dst}) {{
    int {row} = 0, {col} = 0;
    float *__m2c_step_dest = {dst};
    float *__m2c_step_source = {src};
    do {{
        {col} = 0;
        {src} = __m2c_step_dest;
        {dst} = __m2c_step_source;
        do {{
            *{src} = *{dst};
            {col}++;
            {src}++;
            {dst}++;
        }} while ({col} != 3);
        {row}++;
        __m2c_step_dest += 4;
        __m2c_step_source += 4;
    }} while ({row} != 3);
}}'''


def _clear(name, roles, halfwords):
    base, count, cursor = (roles[key] for key in ('base', 'count', 'cursor'))
    if halfwords:
        return f'''void {name}(short *{base}) {{
    int {count};
    short *{cursor};
    for ({count} = 0, {cursor} = {base}; {count} != 8;) {{
        {count} += 4;
        {cursor}[1] = 0;
        {cursor}[2] = 0;
        {cursor}[3] = 0;
        {cursor} += 4;
        {cursor}[-4] = 0;
    }}
}}'''
    # IDO schedules the initial values differently when the loop setup spans source lines.
    stores = ''.join(f'        *(int *)({cursor} + {offset}) = 0;\n' for offset in (56, 60, 64, 68))
    return f'''void {name}(void *{base}) {{
    int {count};
    char *{cursor};
    ((char *){base})[0x99] = 1;
    *(int *)((char *){base} + 0x38) = 0;
    *(int *)((char *){base} + 0x3C) = 0;
    {count} = 2; {cursor} = (char *){base} + 8; do {{
        {count} += 4;
{stores}        {cursor} += 16;
    }} while ({count} != 14);
}}'''
