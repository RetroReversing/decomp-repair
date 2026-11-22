from decomprepair.measured_flag_reload import variants

SOURCE = '''
#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
s32 error(void);
void update(void *obj) {
    s32 old;
    s32 value;
    if ((u32) (error() - 0x501) < 0x5FFU) {
        value = M2C_FIELD(obj, s32 *, 20) | 0x20;
    } else {
        value = M2C_FIELD(obj, s32 *, 20) & ~0x20;
    }
    old = M2C_FIELD(obj, s32 *, 20);
    M2C_FIELD(obj, s32 *, 20) = value;
    if (old & 0x80) {
        M2C_FIELD(obj, s32 *, 20) = (s32) (old & ~0x20);
    }
}
'''.replace('error(void)', 'error()')
ROWS = [
    ('|', 'beqz $v0, 48', 'beql $v0, $zero, 48'),
    ('r', 'addiu $v1, $zero, -33', 'addiu $v0, $zero, -33'),
    ('o', '', 'lw $v1, 20($s0)'),
    (' ', 'sw $v0, 20($s0)', 'sw $v0, 20($s0)'),
    ('o', 'lw $v1, 20($s0)', ''),
    (' ', 'andi $v0, $v1, 128', 'andi $v0, $v1, 128'),
]


def test_restore_observed_flag_reload():
    [(family, candidate)] = variants(SOURCE, 'update', '', ROWS)
    assert family == 'measured_flag_reload'
    assert '__repair_flag_call = error();' in candidate
    assert 'volatile s32 *' in candidate
    assert candidate.index('= value;') < candidate.index('old = M2C_FIELD')


def test_reject_unsafe_or_unproven_shapes():
    for source, header, rows in [
        (SOURCE, '', []),
        (SOURCE.replace('old & 0x80', 'old & 0x20'), '', ROWS),
        (SOURCE.replace('s32 old;', 'volatile s32 old;'), '', ROWS),
        (SOURCE.replace('if ((u32)', 'use(&old); if ((u32)'), '', ROWS),
        (SOURCE.replace('s32 error();', 's32 error(s32);'), '', ROWS),
        (SOURCE, '#define error() something()', ROWS),
        (SOURCE, '#undef M2C_FIELD', ROWS),
        (SOURCE.replace('(*(type_ptr)', '(effect(), *(type_ptr)'), '', ROWS),
    ]:
        assert variants(source, 'update', header, rows) == []
