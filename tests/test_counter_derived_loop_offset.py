from decomprepair.counter_derived_loop_offset import FAMILY, variants

SOURCE = '''void f(void) {
    s32 i;
    s32 offset;
    i = 0;
    mode = 4;
    offset = 0;
    do {
        *(s32 *)(table + offset) = mode;
        i += 1;
        offset += 40;
    } while (i < 32);
}'''
ASM = '''sw $a0, %lo(table)($at)
addiu $a1, $a1, 1
slti $v0, $a1, 0x20
bnez $v0, .Lloop
addiu $v1, $v1, 0x28
'''


def test_recomputes_the_offset_from_the_incremented_counter():
    [(family, child)] = variants(SOURCE, 'f', 'mips', ASM)
    assert family == FAMILY
    assert child == SOURCE.replace('offset += 40;', 'offset = (i << 5) + (i << 3);')


def test_requires_zero_setup_unchanged_locals_and_the_target_loop_tail():
    assert not variants(SOURCE.replace('offset = 0;', 'offset = 4;'), 'f', 'mips', ASM)
    assert not variants(SOURCE.replace('s32 i;', 'volatile s32 i;'), 'f', 'mips', ASM)
    assert not variants(SOURCE.replace('i += 1;', 'call(&offset); i += 1;'), 'f', 'mips', ASM)
    assert not variants(SOURCE, 'f', 'mips', ASM.replace('0x28', '0x30'))
