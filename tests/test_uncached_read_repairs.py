from decomprepair.uncached_read_repairs import applies, rewrite

ASM = '''
glabel fetch
sw $s2, 8($sp)
addu $s2, $a0, $zero
sw $s3, 12($sp)
addu $s3, $a1, $zero
jal ready
nop
bnez $v0, .Lexit
addiu $v0, $zero, -1
lui $v0, %hi(D_A0000000)
or $v0, $s2, $v0
lw $v1, %lo(D_A0000000)($v0)
addu $v0, $zero, $zero
sw $v1, 0($s3)
.Lexit:
lw $ra, 16($sp)
jr $ra
nop
'''

SOURCE = '''
extern M2C_UNK D_A0000000;
s32 ready(void);

s32 fetch(s32 word, s32 *output) {
    s32 code;
    if (word & 3) {
        check(word);
    }
    code = -1;
    if (ready() == 0) {
        code = 0;
        *output = *(word | (s32) &D_A0000000);
    }
    return code;
}
'''


def test_uncached_read_recovers_a_typed_word_and_the_early_error_return():
    assert applies(ASM)
    for source in (SOURCE, SOURCE.replace('*(word |', '*(s32 *)(word |')):
        result = rewrite(source,'fetch',ASM)
        assert 'if (ready() != 0) {\n        return -1;' in result
        assert '*output = *(s32 *)(word | 0xA0000000);' in result
        assert 'check(word);' in result
        assert 's32 code;' not in result


def test_rule_requires_word_width_writeback_input_registers_and_status_lifetime():
    assert not rewrite(SOURCE,'fetch',ASM.replace('lw $v1','lh $v1'))
    assert not rewrite(SOURCE,'fetch',ASM.replace('sw $v1, 0($s3)','sw $v0, 0($s3)'))
    assert not rewrite(SOURCE,'fetch',ASM.replace('$s3, $a1, $zero','$s3, $a2, $zero'))
    assert not rewrite(SOURCE,'fetch',ASM.replace('jal ready','jal other'))
    assert not rewrite(SOURCE.replace('check(word);', 'check(&code);'),'fetch',ASM)
    assert not rewrite(SOURCE,'fetch',ASM,lambda symbol: 0xB0000000)


def test_accepts_the_output_save_in_the_call_delay_slot():
    measured = ASM.replace('addu $s3, $a1, $zero\njal ready\nnop', 'jal ready\naddu $s3, $a1, $zero')
    assert rewrite(SOURCE, 'fetch', measured) == rewrite(SOURCE, 'fetch', ASM)
    assert rewrite(SOURCE, 'fetch', measured.replace('addu $s3, $a1, $zero', 'move $s3, $a1'))
    assert not rewrite(SOURCE, 'fetch', measured.replace('addu $s3, $a1, $zero', 'move $s3, $a2'))
    assert not rewrite(SOURCE, 'fetch', measured.replace('addu $s3, $a1, $zero', 'move $s4, $a1'))
    assert not rewrite(SOURCE, 'fetch', measured.replace('jal ready', 'move $s3, $zero\njal ready'))
    assert not rewrite(SOURCE, 'fetch', measured.replace('jal ready', 'move $a1, $zero\njal ready'))
