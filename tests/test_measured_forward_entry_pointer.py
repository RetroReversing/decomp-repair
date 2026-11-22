from decomprepair.measured_forward_entry_pointer import variants

SOURCE = '''M2C_UNK follow(M2C_UNK); /* extern */
void emit(void *ctx, s32 word) {
    void *out;
    out = M2C_FIELD(ctx, void **, 20);
    M2C_FIELD(ctx, void **, 20) = (void *)(out + 8);
    M2C_FIELD(out, s32 *, 0) = 0x12340007;
    M2C_FIELD(out, s32 *, 4) = word;
    follow(0x12340007);
}'''
ASM = '''glabel emit
addiu $sp, $sp, -24
sw $ra, 16($sp)
lw $v1, 20($a0)
lui $a2, 0x1234
ori $a2, $a2, 7
addiu $v0, $v1, 8
sw $v0, 20($a0)
sw $a2, 0($v1)
jal follow
sw $a1, 4($v1)
lw $ra, 16($sp)
jr $ra
addiu $sp, $sp, 24
endlabel emit'''
ROWS = [(' ', 'jal follow', 'jal follow')]


def test_forwards_entry_pointer_instead_of_literal():
    label, fixed = variants(SOURCE, 'emit', '', ROWS, ASM)[0]
    assert label == 'measured_forward_entry_pointer'
    assert 'follow(void *)' in fixed
    assert 'follow(ctx);' in fixed
    assert 'M2C_FIELD(out, s32 *, 0) = 0x12340007;' in fixed


def test_requires_proven_pointer_and_unambiguous_source():
    assert not variants(SOURCE, 'emit', '', ROWS, ASM.replace('jal follow', 'move $a0, $zero\njal follow'))
    assert not variants(SOURCE, 'emit', '', ROWS, ASM.replace('sw $a1, 4($v1)', 'move $a0, $zero'))
    assert not variants(SOURCE.replace('follow(0x12340007);', 'ctx = out; follow(0x12340007);'), 'emit', '', ROWS, ASM)
    assert not variants(SOURCE, 'emit', 'void follow(int);', ROWS, ASM)
    assert not variants(SOURCE.replace('follow(0x12340007);', 'follow(0x12340007); follow(1);'), 'emit', '', ROWS, ASM)
    assert not variants(SOURCE, 'emit', '#define ctx other', ROWS, ASM)
