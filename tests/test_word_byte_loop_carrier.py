import pytest

from decomprepair.word_byte_loop_carrier import variants

SOURCE = """int locate(u8 *items, u8 key) {
    s16 i;
    u8 probe;
    if (items != 0) {
        probe = key;
        if (probe == 255) return -1;
        i = 0;
        do {
            if (items[i] == probe) return i;
            i++;
        } while (i < 16);
    }
    return -1;
}"""
ASM = """addu $t0, $a1, $zero
andi $a3, $t0, 0xff
addu $v1, $a3, $zero
lbu $v0, 0x8($a2)
beq $v0, $v1, .Lfound"""


def test_stage_word_carrier_with_separate_narrow_comparison():
    [(family, rewritten)] = variants(SOURCE, 'locate', 'mips', ASM)
    assert family == 'word_byte_loop_carrier'
    assert 's32 probe;' in rewritten
    assert 'probe = (u8)key;' in rewritten
    assert 'if (probe == 255)' in rewritten
    assert 'if (items[i] == (u8)key)' in rewritten


@pytest.mark.parametrize('source,asm', [
    (SOURCE, ASM.replace('0xff', '0xffff')),
    (SOURCE, ASM.replace('beq $v0, $v1', 'beq $v0, $a0')),
    (SOURCE.replace('i = 0;', 'i = 0; key++;'), ASM),
    (SOURCE.replace('i = 0;', 'i = sizeof(probe);'), ASM),
])
def test_requires_stable_byte_and_aligned_register_flow(source, asm):
    assert variants(source, 'locate', 'mips', asm) == []
