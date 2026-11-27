from decomprepair.target_indexed_base_reread import variants

SOURCE = '''void f(void *root, int i) {
    char *first;
    char *next;
    int value;
    float result;
    first = (u8 *) root + 0x60;
    first = *(u8 **) first + i * 0x10;
    callback();
    next = first;
    value = (u8)(((u8 *)first)[0xA]);
    result = M2C_FIELD(next, f32 *, 0xC);
}
'''
ASM = '''jal func
lw $v1, 0x60($s2)
sll $v0, $s5, 4
lwc1 $fs0, 0x28($s1)
addu $v0, $v0, $v1
lwc1 $fv0, 0xC($v0)
mul.s $fs0, $fs0, $fv0
lbu $s0, 0xA($v0)
'''


def test_rereads_both_fields_after_call():
    result = variants(SOURCE, 'f', ASM)
    assert len(result) == 1
    assert 'next = *(u8 **)((u8 *) root + 0x60) + i * 0x10;' in result[0][1]
    assert '((u8 *)next)[0xA]' in result[0][1]


def test_requires_target_offsets_and_intervening_call():
    for asm in ('', ASM.replace('jal func\n', ''), ASM.replace('0x60($s2)', '0x64($s2)'), ASM.replace('0xA($v0)', '0xB($v0)'),
                ASM.replace('0xC($v0)', '0x10($v0)')):
        assert not variants(SOURCE, 'f', asm)
    assert not variants(SOURCE.replace('    callback();\n', ''), 'f', ASM)
    assert not variants(SOURCE.replace('    callback();', '    i++; callback();'), 'f', ASM)
