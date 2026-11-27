from decomprepair.masked_loop_copy import variants

SOURCE = '''
void f(void *root, u8 value) {
    u8 phase;
    int offset;
    void *cursor;
    phase = value & 0xff;
    offset = phase * 0x10;
    call(offset);
    cursor = M2C_FIELD(root, void **, 0x64);
    while (cursor != NULL) {
        if (M2C_FIELD(cursor, u8 *, 0x31) == phase) {
            use(cursor);
        }
        cursor = M2C_FIELD(cursor, void **, 0);
    }
}
'''
ASM = '''
andi $s4, $s5, 0xff
sll $s0, $s4, 4
jal helper
addu $s0, $s4, $zero
'''


def test_widens_and_splits_together():
    result = variants(SOURCE, 'f', ASM, ['-mgp32'])
    assert len(result) == 1
    child = result[0][1]
    assert 'u32 phase;' in child
    assert '__repair_masked_loop_copy = phase;' in child
    assert '== __repair_masked_loop_copy)' in child


def test_requires_mask_copy_and_unmodified_value():
    assert variants(SOURCE, 'f', ASM.replace('$s4, $zero', '$s3, $zero'), ['-mgp32']) == []
    assert variants(SOURCE, 'f', ASM, []) == []
    assert variants(SOURCE.replace('call(offset);', 'phase = 1; call(offset);'), 'f', ASM, ['-mgp32']) == []
    assert variants(SOURCE.replace('u8 phase;', 'volatile u8 phase;'), 'f', ASM, ['-mgp32']) == []
