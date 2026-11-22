from decomprepair.measured_kmc_relocated_pool import variants

SOURCE = '''extern M2C_UNK state;
void f(void) {
    s32 *cursor;
    cursor = (M2C_FIELD(&state, s32 *, 0x18) * 4) + ((char *)&state + 0x10);
    *cursor += 0x60;
}'''
TARGET = '''lui $v1, %hi(index)
lw $v1, %lo(index)($v1)
lui $v0, %hi(table)
addiu $v0, $v0, %lo(table)
sll $v1, $v1, 2
addu $v1, $v1, $v0
lw $v0, ($v1)
addiu $a0, $v0, 96
jr $ra
sw $a0, ($v1)'''.splitlines()
ROWS = [(' ', line, line) for line in TARGET]
ROWS[0] = ('r', TARGET[0], 'lui $v0, %hi(index)')
ROWS.insert(1, ('>', '', 'addiu $v0, $v0, %lo(index)'))
RESOLVE = {'state': 0x1000, 'index': 0x1018, 'table': 0x1010}.get


def test_stages_proven_relocated_pool():
    label, fixed = variants(SOURCE, 'f', '', ROWS, RESOLVE)[0]
    assert label == 'measured_relocated_pool_cursor'
    assert 'extern s32 index;' in fixed
    assert 'extern s32 table;' in fixed
    assert 'cursor = &table;' in fixed
    assert '__repair_index = index;' in fixed
    assert 'cursor += __repair_index;' in fixed


def test_requires_target_and_matching_addresses():
    assert not variants(SOURCE, 'f', '', ROWS, lambda _: None)
    assert not variants(SOURCE.replace('0x18', '0x1C'), 'f', '', ROWS, RESOLVE)
    assert not variants(SOURCE.replace('0x60', '0x40'), 'f', '', ROWS, RESOLVE)
    assert not variants(SOURCE, 'f', 'extern s32 index;', ROWS, RESOLVE)
    assert not variants(SOURCE.replace('s32 *cursor', 'volatile s32 *cursor'), 'f', '', ROWS, RESOLVE)
    assert not variants(SOURCE, 'f', '', [(' ', line, line) for line in TARGET], RESOLVE)
