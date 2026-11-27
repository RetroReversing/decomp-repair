from decomprepair.target_byte_index_scale import variants

SOURCE = '''void f(void *p, int i) {
    use(M2C_FIELD(((i * 4) + M2C_FIELD(p, s16 **, 0x20)), s32 *, 0xC));
}
'''
ASM = '''lw $a0, 0x20($s2)
lh $v0, 0($a0)
slt $v0, $v1, $v0
beqz $v0, exit
sll $v0, $v1, 2
addu $v0, $v0, $a0
lw $a1, 0xC($v0)
'''


def test_observed_word_index_repairs_double_scaling():
    children = variants(SOURCE, 'f', ASM)
    assert len(children) == 1
    assert '(u8 *) M2C_FIELD(p, s16 **, 0x20)' in children[0][1]


def test_requires_the_same_target_base_and_access():
    for asm in ('', ASM.replace('0x20($s2)', '0x24($s2)'), ASM.replace('0xC($v0)', '0x10($v0)'),
                ASM.replace('lh $v0', 'lw $v0'), ASM.replace('$v0, $v0, $a0', '$v0, $v0, $a1')):
        assert not variants(SOURCE, 'f', asm)
