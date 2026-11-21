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


PREFACED_SOURCE = '''
M2C_UNK block_read(M2C_UNK *, M2C_UNK); /* extern */
u16 decode16(M2C_UNK *); /* extern */
s32 decode32(M2C_UNK *); /* extern */
s32 f(void) {
    M2C_UNK sp10;
    M2C_UNK sp12;
    M2C_UNK sp14;
    M2C_UNK sp16;
    s32 temporary;
    block_read(&sp10, 0xC);
    M2C_FIELD(&state, u16 *, 0x12) = decode16(&sp12);
    M2C_FIELD(&state, u16 *, 0x14) = decode16(&sp14);
    M2C_FIELD(&state, s32 *, 0x18) = decode32(&sp16);
    if (M2C_FIELD(&state, u16 *, 0x12) & 8) {
        temporary = refresh();
        M2C_FIELD(&state, s32 *, 0x18) = temporary;
    }
    return 0;
}
'''
PREFACED_ASM = '''
addiu $sp, $sp, -56
addiu $a0, $sp, 16
addiu $a1, $zero, 12
sw $ra, 52($sp)
jal block_read
sw $s0, 48($sp)
jal decode16
addiu $a0, $sp, 18
addiu $a0, $sp, 20
lui $s0, %hi(state + 18)
addiu $s0, $s0, %lo(state + 18)
jal decode16
sh $v0, 0($s0)
lui $at, %hi(state + 20)
sh $v0, %lo(state + 20)($at)
jal decode32
addiu $a0, $sp, 22
move $a2, $s0
lui $at, %hi(state + 24)
sw $v0, %lo(state + 24)($at)
beqz $a2, .Lend
nop
.Lend:
lw $ra, 52($sp)
lw $s0, 48($sp)
jr $ra
addiu $sp, $sp, 56
'''


def test_header_decoder_can_save_its_first_result_in_the_next_call_delay_slot():
    assert applies(PREFACED_ASM)
    fixed = rewrite(PREFACED_SOURCE, 'f', PREFACED_ASM)
    assert 'u8 __repair_header_bytes[12];' in fixed
    assert 'u16 decode16(void *);' in fixed
    assert 'M2C_FIELD(&state, u16 *, 0x12) = decode16(__repair_header_bytes + 2);' in fixed
    tail = PREFACED_SOURCE.split('    if (')[1]
    assert fixed.split('    if (')[1] == tail
    assert not applies(PREFACED_ASM.replace('jal decode16\nsh', 'move $s0, $a2\njal decode16\nsh'))
    assert not applies(PREFACED_ASM.replace('move $a2, $s0', 'move $v0, $s0'))
    assert not applies(PREFACED_ASM.replace('addiu $a0, $sp, 22', 'addiu $a0, $sp, 26'))
    assert not rewrite(PREFACED_SOURCE.replace('refresh()', 'refresh(&sp16)'), 'f', PREFACED_ASM)
