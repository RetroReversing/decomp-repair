"""Put an IDO unrolled float matrix copy back into typed nested loops."""

import re

from .integer_repair_support import IDENT, edit, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines
from .pattern_repairs import close
from .shared_default_drafts import _instructions

FAMILY = 'ido_unrolled_matrix_copy'
_SOURCE = _shape('''
    s32 @row; void *@next; void *@third; void *@from; void *@to;
    @from = @source; @row = 0; @to = @dest;
    do { @next = @from + 4;
    M2C_FIELD(@to, f32 *, 0) = (f32) M2C_FIELD(@from, f32 *, 0);
    @third = @next + 4;
    M2C_FIELD(@to, f32 *, 4) = (f32) M2C_FIELD(@from, f32 *, 4);
    M2C_FIELD(@to, f32 *, 8) = (f32) M2C_FIELD(@next, f32 *, 4);
    @row += 1; @from = @third + 4 + 4; @to += 0x10;
    M2C_FIELD(@to, f32 *, -4) = (f32) M2C_FIELD(@third, f32 *, 4);
    } while (@row != 4);
    return @dest;
''')
_TARGET = '''or $v0, $zero, $zero
or $a2, $a0, $zero
addiu $a3, $zero, 4
or $v1, $a1, $zero
lwc1 $ft0, 0($v1)
addiu $a1, $a1, 4
or $v1, $a1, $zero
swc1 $ft0, 0($a2)
lwc1 $ft1, 0($v1)
addiu $a1, $a1, 4
or $v1, $a1, $zero
swc1 $ft1, 4($a2)
lwc1 $ft2, 0($v1)
addiu $a1, $a1, 4
or $v1, $a1, $zero
swc1 $ft2, 8($a2)
lwc1 $ft3, 0($v1)
addiu $v0, $v0, 1
addiu $a1, $a1, 4
addiu $a2, $a2, 16
bne $v0, $a3, @3
swc1 $ft3, -4($a2)
jr $ra
or $v0, $a0, $zero'''


def applies(asm):
    if not asm or 'swc1' not in asm or 'lwc1' not in asm:
        return False
    lines, labels = _instructions(asm)
    if len(lines) != 24:
        return False
    rows = list(normalized_integer_lines(lines))
    branch, _, label = rows[20].rpartition(', ')
    if label not in labels:
        return False
    rows[20] = f'{branch}, @{labels[label]}'
    for i, row in enumerate(rows):
        for reg, alias in ((4, 'ft0'), (6, 'ft1'), (8, 'ft2'), (10, 'ft3')):
            row = re.sub(rf'\$f{reg}\b', f'${alias}', row)
        rows[i] = row
    return '\n'.join(rows) == _TARGET


def rewrite(source, name, asm, header=''):
    if not source or 'M2C_FIELD(' not in source or '_m2c_copy_' in source + header or not applies(asm):
        return None
    part = view(source, name)
    closing = close(part.clean, part.opening, '{', '}') if part else None
    if not closing:
        return None
    sig = re.search(rf'\bvoid \*{re.escape(name)}\(void \*(?P<dest>{IDENT}), void \*(?P<src>{IDENT})\)\s*$',
                    part.clean[:part.opening])
    if not sig or re.search(rf'\b{re.escape(name)}\s*\(', header + part.clean[:sig.start()]):
        return None
    match = _SOURCE.fullmatch(' '.join(part.clean[part.opening + 1:closing - 1].split()))
    if not match or (match['dest'], match['source']) != sig.groups():
        return None
    dst, src = sig.groups()
    return edit(source, [(sig.start(), closing, f'''f32 *{name}(f32 (*{dst})[4], f32 *{src}) {{
    int _m2c_copy_row, _m2c_copy_col;
    f32 *_m2c_copy_word;

    /* IDO schedules the cursor advances differently when these start on separate lines. */
    for (_m2c_copy_row = 0; _m2c_copy_row < 4; _m2c_copy_row++) {{ for (_m2c_copy_col = 0; _m2c_copy_col < 4; _m2c_copy_col++) {{
        _m2c_copy_word = {src}++;
        {dst}[_m2c_copy_row][_m2c_copy_col] = *_m2c_copy_word;
    }} }}
    return (f32 *){dst};
}}''')])
