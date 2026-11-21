from decomprepair.measured_kmc_pointer_table_guard import variants

SOURCE = '''extern M2C_UNK table;
void f(void *object) {
    u16 flags;
    s32 slot;
    flags = M2C_FIELD(object, u16 *, 0x560);
    if (!(flags & 8) && ((flags & 7) < 5)) {
        slot = call();
        *(&table + ((slot & 0xFFFF) * 0x64)) = object;
    }
}'''
ROWS = [(' ', 'nop', 'nop')] * 38 + [
    (' ', 'andi $v0, $v1, 7', 'andi $v0, $v1, 7'),
    ('|', 'slti $v0, $v0, 5', 'sltiu $v0, $v0, 5'),
    ('i', 'sll $v0, $v0, 2', 'sll $v0, $v0, 4'),
    (' ', 'lui $at, %hi(table)', 'lui $at, %hi(table)'),
    (' ', 'addu $at, $at, $v0', 'addu $at, $at, $v0'),
    (' ', 'sw $s0, %lo(table)($at)', 'sw $s0, %lo(table)($at)')]


def test_recover_guard_and_pointer_stride():
    label, fixed = variants(SOURCE, 'f', '', ROWS)[0]
    assert label == 'measured_signed_guard_pointer_stride'
    assert '(((s16)flags & 7) < 5)' in fixed
    assert '*(void **)((char *)&table + ((slot & 0xFFFF) * 0x64)) = object;' in fixed


def test_requires_evidence_and_source_types():
    assert not variants(SOURCE, 'f', '', ROWS[:-1])
    assert not variants(SOURCE.replace('u16 flags;', 's32 flags;'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('* 0x64', '* 0x68'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('M2C_UNK table', 's32 table'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('u16 flags;', 'volatile u16 flags;'), 'f', '', ROWS)
