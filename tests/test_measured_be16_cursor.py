from decomprepair.measured_be16_cursor import variants

SOURCE = '''
#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
void *read16(void *obj, void *src) {
    M2C_FIELD(obj, s16 *, 0xAA) = (s16) (M2C_FIELD(src, u8 *, 1) | (M2C_FIELD(src, u8 *, 0) << 8));
    M2C_FIELD(obj, s16 *, 0xAC) = 0;
    return src + 1 + 1;
}
'''
ROWS = [
    ('i', 'lbu $v1, ($a1)', 'lbu $v1, 1($a1)'),
    ('<', 'addiu $a1, $a1, 1', ''),
    (' ', 'lbu $v0, ($a1)', 'lbu $v0, ($a1)'),
    (' ', 'sh $zero, 0xac($a0)', 'sh $zero, 0xac($a0)'),
    ('r', 'sll $v1, $v1, 8', 'sll $v0, $v0, 8'),
    ('r', 'or $v0, $v0, $v1', 'or $v1, $v1, $v0'),
    ('>', '', 'addiu $v0, $a1, 2'),
    ('o', '', 'jr $ra'),
    ('r', 'sh $v0, 0xaa($a0)', 'sh $v1, 0xaa($a0)'),
    ('o', 'jr $ra', ''),
    ('<', 'addiu $v0, $a1, 1', ''),
]


def test_stage_big_endian_cursor_reads():
    [(family, candidate)] = variants(SOURCE, 'read16', '', ROWS)
    assert family == 'measured_be16_cursor'
    assert 'void *obj, u8 *src' in candidate
    assert '__repair_be16_hi = *src++;' in candidate
    assert '__repair_be16_lo = *src;' in candidate
    assert 'return src + 1;' in candidate


def test_reject_unsafe_or_unproven_rewrites():
    for source, header, rows in [
        (SOURCE, '', []),
        (SOURCE.replace('void *src', 'volatile void *src'), '', ROWS),
        (SOURCE.replace('s16 *, 0xAC', 's16 *, 0xAB'), '', ROWS),
        (SOURCE.replace('return src + 1 + 1;', 'use(src); return src + 1 + 1;'), '', ROWS),
        (SOURCE, 'void *read16(void *, void *);', ROWS),
        (SOURCE, '#define src other()', ROWS),
        (SOURCE, '#undef M2C_FIELD', ROWS),
        (SOURCE.replace('(*(type_ptr)', '(effect(), *(type_ptr)'), '', ROWS),
    ]:
        assert variants(source, 'read16', header, rows) == []
