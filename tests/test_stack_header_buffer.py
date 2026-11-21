from decomprepair.stack_header_buffer import applies, rewrite

SOURCE = '''
s16 read_half(M2C_UNK *); /* extern */
s32 read_word(M2C_UNK *); /* extern */
M2C_UNK read_block(M2C_UNK *, M2C_UNK); /* extern */
extern M2C_UNK records;

s32 read_header(void) {
    M2C_UNK sp10;
    M2C_UNK sp14;
    M2C_UNK sp16;

    read_block(&sp10, 0xA);
    M2C_FIELD(&records, s16 *, 8) = read_half(&sp14);
    M2C_FIELD(&records, s32 *, 0xC) = read_word(&sp16);
    return 0;
}
'''

ASM = '''
addiu $sp, $sp, -32
addiu $a0, $sp, 16
sw $ra, 28($sp)
jal read_block
addiu $a1, $zero, 10
jal read_half
addiu $a0, $sp, 20
lui $at, %hi(records + 8)
sh $v0, %lo(records + 8)($at)
jal read_word
addiu $a0, $sp, 22
lui $at, %hi(records + 12)
sw $v0, %lo(records + 12)($at)
lw $ra, 28($sp)
addu $v0, $zero, $zero
jr $ra
addiu $sp, $sp, 32
'''


def test_stack_header_uses_one_byte_buffer_for_the_read_and_each_decoder():
    assert applies(ASM)
    fixed = rewrite(SOURCE, 'read_header', ASM)
    assert 'u8 __repair_header_bytes[10];' in fixed
    assert 'read_block(__repair_header_bytes, 10);' in fixed
    assert 'read_half(__repair_header_bytes + 4);' in fixed
    assert 'read_word(__repair_header_bytes + 6);' in fixed
    assert 'read_word(void *);' in fixed
    assert 'sp16' not in fixed


def test_stack_header_requires_contained_fields_and_m2c_placeholders():
    assert not applies(ASM.replace('22\nlui', '23\nlui'))
    assert not applies(ASM.replace('%lo(records + 12)', '%lo(records + 16)'))
    assert rewrite(SOURCE.replace('read_word(&sp16)', 'read_word(&sp14)'), 'read_header', ASM) is None
    assert rewrite(SOURCE.replace('read_word(M2C_UNK *); /* extern */',
                                  'read_word(M2C_UNK *);'), 'read_header', ASM) is None
    assert rewrite(SOURCE, 'read_header', ASM, 'int read_word(void *);') is None
