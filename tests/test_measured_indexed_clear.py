from decomprepair.measured_indexed_clear import variants

SOURCE = '''
extern s32 base;
void clear(s32 slot) {
    s32 i;
    i = 0;
    do {
        *(s32 *)(((i & 0xFF) * 4) + (((slot & 0xFF) * 0x38) + base + 0xAC)) = 0;
        i += 1;
    } while ((u32) (i & 0xFF) < 0xEU);
}
'''
ROWS = [
    (' ', 'move $a1, $zero', 'move $a1, $zero'),
    ('o', 'lui $v1, %hi(base)', ''),
    ('o', 'lw $v1, %lo(base)($v1)', ''),
    (' ', 'andi $a0, $a0, 0xff', 'andi $a0, $a0, 0xff'),
    ('o', '', 'lui $v1, %hi(base)'),
    ('o', '', 'lw $v1, %lo(base)($v1)'),
    ('i', 'addiu $v1, $v0, 0xac', 'addiu $a1, $a1, 1'),
    ('i', 'sw $zero, ($v0)', 'sw $zero, 0xac($v0)'),
]


def test_stage_global_and_displacement():
    [(family, candidate)] = variants(SOURCE, 'clear', '', ROWS)
    assert family == 'measured_indexed_clear'
    assert '__repair_clear_global = base;' in candidate
    assert '__repair_clear_offset = 0xAC;' in candidate
    assert '+ __repair_clear_global + __repair_clear_offset' in candidate


def test_decline_unobserved_or_effectful_loops():
    for source, header, rows in [
        (SOURCE, '', []),
        (SOURCE.replace('extern s32 base;', 'extern volatile s32 base;'), '', ROWS),
        (SOURCE.replace('i += 1;', 'use(i); i += 1;'), '', ROWS),
        (SOURCE.replace('i += 1;', 'i += 2;'), '', ROWS),
        (SOURCE.replace('s32 i;', 'static s32 i;'), '', ROWS),
        (SOURCE, '#define base other()', ROWS),
        (SOURCE, 'typedef volatile int s32;', ROWS),
        (SOURCE, 'extern int base;', ROWS),
    ]:
        assert variants(source, 'clear', header, rows) == []
