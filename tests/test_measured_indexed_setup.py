from decomprepair import measured_indexed_setup as repair

HEADER = 'typedef signed int s32; typedef signed char s8; typedef signed short s16; typedef unsigned char u8;'
SOURCE = '''typedef s32 M2C_UNK;
#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
extern M2C_UNK state;
extern void *current;
extern M2C_UNK callback1, callback2;
s32 setup(s32 a, M2C_UNK b) {
    if (M2C_FIELD(M2C_FIELD(&state, void **, 4), s16 *, 2) == 5) {
        read_item(M2C_FIELD((M2C_FIELD(&state, s32 *, 16) + M2C_FIELD(current, s8 *, 8)), u8 *, 12));
        finish();
    }
    reset(a, b);
    M2C_FIELD(current, s8 *, 20) = 0;
    M2C_FIELD(current, M2C_UNK **, 24) = &callback1;
    M2C_FIELD(current, M2C_UNK **, 28) = &callback2;
    M2C_FIELD(current, s8 *, 32) = 0;
    return 0;
}
'''
ROWS = [('r', op, '') for op in [
    'lui $v1, %hi(table)', 'lw $v1, %lo(table)($v1)', 'lb $v0, 8($v0)', 'addu $v1, $v1, $v0',
    'jal read_item', 'lbu $a0, 12($v1)', 'lui $a0, %hi(current)', 'lw $a0, %lo(current)($a0)',
    'sb $zero, 20($a0)', 'lui $a1, %hi(current)', 'lw $a1, %lo(current)($a1)',
    'sw $v1, 24($a0)', 'sw $v1, 28($a0)', 'sb $zero, 32($a1)',
]]


def variants(source=SOURCE, header=HEADER, rows=ROWS, flags=('-mgp32',), addresses=None):
    addresses = addresses if addresses is not None else {'state': 0x1000, 'table': 0x1010}
    return repair.variants(source, 'setup', header, rows, flags, addresses.get)


def test_stages_table_and_separate_pointer_snapshots():
    (_, candidate), = variants()
    assert '__repair_table = M2C_FIELD(&state, s32 *, 16);' in candidate
    assert candidate.index('__repair_first = current;') < candidate.index('__repair_last = current;')
    assert 'M2C_FIELD(__repair_first, M2C_UNK **, 24)' in candidate
    assert 'M2C_FIELD(__repair_last, s8 *, 32)' in candidate


def test_requires_matching_symbols_instruction_shape_and_safe_types():
    assert not variants(addresses={'state': 0x1000, 'table': 0x1014})
    assert not variants(rows=ROWS[:-1])
    assert not variants(flags=('-mabi=64',))
    assert not variants(header=HEADER.replace('signed int', 'volatile int'))
    assert not variants(source=SOURCE.replace('finish();', 'finish(); other();'))
    assert not variants(header=HEADER + '\n#define read_item(x) another(x)')
    assert not variants(source=SOURCE.replace('reset(a, b);', '/* keep */ reset(a, b);'))
