from decomprepair.measured_wide_division_stride import variants

SOURCE = '''u64 __udivdi3(s32, s32, M2C_UNK, M2C_UNK);
s32 sample(void) {
    void *entry;
    entry = M2C_FIELD(&base, s32 **, 0x20) + (*M2C_FIELD(&base, s32 **, 0x20) * 8);
    return (u32) __udivdi3(M2C_FIELD(entry, s32 *, 0x48), M2C_FIELD(entry, s32 *, 0x4c), 0, 0xfa) + 0x28;
}
'''
T = ['lw $v0, ($v1)', 'sll $v0, $v0, 3', 'addu $v1, $v1, $v0', 'lw $a0, 0x48($v1)',
     'lw $a1, 0x4c($v1)', 'addiu $a2, $zero, 0', 'jal __udivdi3', 'addiu $a3, $zero, 0xfa']
C = T.copy()
C[1] = 'sll $v0, $v0, 5'
ROWS = [('r', a, b) for a, b in zip(T, C)]


def test_uses_byte_stride_and_wide_helper_arguments():
    result = variants(SOURCE, 'sample', '', ROWS)
    assert len(result) == 1
    assert 'u64 __udivdi3(u64, u64);' in result[0][1]
    assert '(char *) M2C_FIELD(&base, s32 **, 0x20)' in result[0][1]
    assert 'M2C_FIELD(entry, u64 *, 0x48), 0xfa' in result[0][1]


def test_requires_matching_stride_offsets_and_unshared_helper():
    assert not variants(SOURCE, 'sample', '', [('r', a, a) for a in T])
    assert not variants(SOURCE.replace('0x4c', '0x50'), 'sample', '', ROWS)
    assert not variants(SOURCE, 'sample', 'u64 __udivdi3(u64, u64);', ROWS)
    assert not variants(SOURCE.replace('void *entry;', 'volatile void *entry;'), 'sample', '', ROWS)
