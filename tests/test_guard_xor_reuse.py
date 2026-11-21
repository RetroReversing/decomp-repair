from decomprepair.guard_xor_reuse import FAMILY, variants

SOURCE = '''void f(void) {
    s32 key;
    s32 changed;
    key = read_key();
    changed = key ^ 0x20;
    if (key == 0x26) {
        different = key != 0x20;
    }
}'''
ASM = 'xori $v0, $s1, 0x20\nlw $a0, 0($a0)\nsltu $v0, $zero, $v0\n'


def test_reuses_the_existing_xor_in_the_guard():
    [(family, child)] = variants(SOURCE, 'f', 'mips', ASM)
    assert family == FAMILY
    assert child == SOURCE.replace('key != 0x20', 'changed != 0')


def test_requires_matching_mask_and_target_value_flow():
    assert not variants(SOURCE.replace('key != 0x20', 'key != 0x21'), 'f', 'mips', ASM)
    assert not variants(SOURCE, 'f', 'mips', ASM.replace('$zero, $v0', '$zero, $v1'))
    assert not variants(SOURCE.replace('s32 changed', 's8 changed'), 'f', 'mips', ASM)
