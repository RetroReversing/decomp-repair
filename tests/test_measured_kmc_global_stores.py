from decomprepair.measured_kmc_global_stores import variants

SOURCE = '''s32 f(void) {
    M2C_FIELD(M2C_FIELD(&owner, void **, 0x10), s32 *, 4) = (s32) M2C_FIELD(&data, s32 *, 0x20);
    M2C_FIELD(M2C_FIELD(&owner, void **, 0x10), s32 *, 0) = (s32) M2C_FIELD(&data, s32 *, 0x30);
    return 1;
}'''
TARGET = '''lui $v1, %hi(ptr)
lw $v1, %lo(ptr)($v1)
lui $v0, %hi(first)
lw $v0, %lo(first)($v0)
sw $v0, 4($v1)
lui $v1, %hi(ptr)
lw $v1, %lo(ptr)($v1)
lui $v0, %hi(second)
lw $v0, %lo(second)($v0)
sw $v0, ($v1)
jr $ra
addiu $v0, $zero, 1'''.splitlines()
ROWS = [(' ', x, x) for x in TARGET]
ROWS[7] = ('<', TARGET[7], '')
RESOLVE = {'owner': 0x1000, 'data': 0x2000, 'ptr': 0x1010, 'first': 0x2020, 'second': 0x2030}.get


def test_repeated_relocated_pointer_load():
    result = variants(SOURCE, 'f', '', ROWS, RESOLVE)
    assert result[0][0] == 'measured_relocated_pointer_stores'
    fixed = result[0][1]
    assert 'extern void * volatile ptr;' in fixed
    assert 'M2C_FIELD(ptr, s32 *, 4) = (s32) first;' in fixed
    assert 'M2C_FIELD(ptr, s32 *, 0) = (s32) second;' in fixed


def test_requires_matching_addresses_and_evidence():
    assert not variants(SOURCE, 'f', '', ROWS, lambda _: 0)
    assert not variants(SOURCE, 'f', 'extern void *ptr;', ROWS, RESOLVE)
    assert not variants(SOURCE, 'f', '', [(' ', x, x) for x in TARGET], RESOLVE)
    assert not variants(SOURCE.replace('0x30', '0x34'), 'f', '', ROWS, RESOLVE)
    assert not variants(SOURCE.replace('s32 f', 'volatile s32 f').replace('return 1;', 'volatile s32 v; return 1;'),
                        'f', '', ROWS, RESOLVE)


def test_word_address_writeback_requires_dead_local_and_relocated_store():
    source = '''extern s32 slot;
void f(void) {
    u32 base;
    base = *((u32 *) ptr);
    slot = base + (((used + 1) << 1) << 5);
    base = *((u32 *) other);
    use(base);
}'''
    rows = [
        ('|', 'addu $v1, $v1, $v0', 'addu $v0, $v1, $v0'),
        (' ', 'lui $at, %hi(target_slot)', 'lui $at, %hi(target_slot)'),
        ('|', 'sw $v1, %lo(target_slot)($at)', 'sw $v0, %lo(target_slot)($at)'),
    ]
    resolve = {'slot': 0x1000, 'target_slot': 0x1000}.get
    assert variants(source, 'f', '', rows, resolve) == [(
        'measured_word_address_writeback',
        source.replace('slot = base + (((used + 1) << 1) << 5);',
                       'base += (((used + 1) << 1) << 5); slot = base;'),
    )]
    assert not variants(source, 'f', '', rows)
    assert not variants(source, 'f', '', rows[:-1], resolve)
    assert not variants(source.replace('base = *((u32 *) other);', 'base = base + 1;'), 'f', '', rows, resolve)
    assert not variants(source.replace('base = *((u32 *) other);', 'if (used) base = 0;'), 'f', '', rows, resolve)
