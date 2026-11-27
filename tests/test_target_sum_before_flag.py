from decomprepair.target_sum_before_flag import variants

SOURCE = '''void f(void *record, void *player, void *object) {
    { void *alias; { { alias = record; } } M2C_FIELD(alias, u8 *, 0x37) = 0U; }
    { { M2C_FIELD(record, s32 *, 0x24) = (s32) (M2C_FIELD(player, s32 *, 0x1C) + M2C_FIELD(M2C_FIELD(object, void **, 0), s32 *, 0)); } }
}
'''
ASM = '''lw $v1, 0($s6)
lw $v0, 0x1c($s2)
lw $v1, 0($v1)
sb $zero, 0x37($s1)
addu $v0, $v0, $v1
sw $v0, 0x24($s1)
'''


def test_target_loads_before_flag():
    out = variants(SOURCE, 'f', ASM)
    assert len(out) == 1
    child = out[0][1]
    assert child.index('s32 time =') < child.index('u8 *, 0x37') < child.index('s32 *, 0x24')


def test_target_must_prove_the_offsets_and_dataflow():
    for asm in ('', ASM.replace('0x1c($s2)', '0x20($s2)'), ASM.replace('0x37($s1)', '0x36($s1)'),
                ASM.replace('0x24($s1)', '0x28($s1)'), ASM.replace('$v0, $v0, $v1', '$v0, $v0, $a1')):
        assert not variants(SOURCE, 'f', asm)
