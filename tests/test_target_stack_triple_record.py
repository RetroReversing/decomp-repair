from decomprepair.target_stack_triple_record import variants

SOURCE = '''void f(void) {
    s16 sp30;
    s16 sp32;
    s8 sp34;
    sp30 = 3; sp32 = 0; sp34 = 0;
    init(&sp30);
}
'''
ASM = '''sh $v0, 0x30($sp)
sh $zero, 0x32($sp)
sb $zero, 0x34($sp)
addiu $a1, $sp, 0x30
jal init
nop
'''


def test_groups_the_target_witnessed_stack_fields():
    result = variants(SOURCE, 'f', ASM)[0][1]
    assert 'struct { s16 first; s16 second; u8 third; }' in result
    assert '__repair_triple.first = 3;' in result
    assert 'init(&__repair_triple.first)' in result


def test_requires_witness_and_no_independent_reads():
    assert not variants(SOURCE, 'f', ASM.replace('sb $zero, 0x34($sp)', 'nop'))
    assert not variants(SOURCE.replace('init(&sp30);', 'use(sp32); init(&sp30);'), 'f', ASM)
    assert not variants(SOURCE.replace('init(&sp30);', 'init(&sp30); use(&sp34);'), 'f', ASM)
    assert not variants(SOURCE, 'f', ASM, '#define second other')
    assert not variants(SOURCE.replace('sp34 = 0;', 'sp34 = 200;'), 'f', ASM)
    assert not variants(SOURCE.replace('    s16 sp32;', '    { s16 sp32; }'), 'f', ASM)
