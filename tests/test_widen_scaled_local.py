from decomprepair.widen_scaled_local import FAMILY, variants

SOURCE = '''void f(void) {
    short size;
    size = 0x800;
    if (expanded != 0) {
        size = 0x4000;
    }
    size *= 8;
    buffer = allocate(size, 0);
    end = buffer + size;
}'''
ASM = 'addiu $s0, $zero, 0x4000\n.Ljoin:\nsll $s0, $s0, 3\n'


def test_keeps_the_scaled_allocation_size_wide():
    [(family, child)] = variants(SOURCE, 'f', 'mips', ASM)
    assert family == FAMILY
    assert 's32 size;\n    s32 __repair_scaled_size;' in child
    assert '__repair_scaled_size = size * 8;' in child
    assert 'buffer = allocate(__repair_scaled_size, 0);' in child
    assert 'end = buffer + __repair_scaled_size;' in child


def test_requires_target_shift_and_rejects_later_writes():
    assert not variants(SOURCE, 'f', 'mips', ASM.replace('3\n', '19\n'))
    assert not variants(SOURCE.replace('end = buffer + size;', 'size++;'), 'f', 'mips', ASM)
    assert not variants(SOURCE.replace('short size;', 's32 size;'), 'f', 'mips', ASM)
