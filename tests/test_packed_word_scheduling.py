from decomprepair.packed_word_scheduling import FAMILY, variants

SOURCE = '''void f(Entry *entry, s16 value) {
    u32 shade = (s32)value;
    entry->color.word = (((0xff000000 | (shade << 8)) | (shade << 16)) | shade);
}'''
ASM = '/* address */ sll $v1, $a1, 0x10\n/* address */ sll $v0, $a1, 8\n'


def test_uses_target_shift_order_and_scope_in_one_trial():
    [(family, child)] = variants(SOURCE, 'f', 'mips', ASM)
    assert family == FAMILY
    assert 'do { entry->color.word = (((0xff000000 | (shade << 16)) | (shade << 8)) | shade); } while (0);' in child


def test_requires_unsigned_local_and_corresponding_target_shifts():
    assert not variants(SOURCE.replace('u32 shade', 'volatile u32 shade'), 'f', 'mips', ASM)
    assert not variants(SOURCE, 'f', 'mips', ASM.replace('$v0, $a1', '$v0, $a0'))
    assert not variants(SOURCE, 'f', 'x86', ASM)
