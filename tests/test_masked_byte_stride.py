import pytest

from decomprepair.counter_derived_loop_offset import MASKED_BYTE_STRIDE, masked_byte_stride_variants

SOURCE = """extern u8 table;
u8 lookup(int value) {
    s32 index;
    index = value & 0xFFFF;
    return *((u8 *)&table + (index * 24));
}"""
ASM = """andi $v0, $a0, 0xFFFF
sll $v1, $v0, 1
addu $v0, $v1, $v0
sll $v0, $v0, 3
lui $a0, %hi(table)
addu $a0, $a0, $v0
lbu $a0, %lo(table)($a0)"""


def test_spells_out_the_target_arithmetic_for_the_bounded_index():
    [(family, candidate)] = masked_byte_stride_variants(SOURCE, 'lookup', 'mips', ASM)
    assert family == MASKED_BYTE_STRIDE
    assert '((index + (index << 1)) << 3)' in candidate


@pytest.mark.parametrize('source,asm', [
    (SOURCE.replace('0xFFFF;', '0x7FFFFFFF;'), ASM),
    (SOURCE.replace('index * 24', 'index * 32'), ASM),
    (SOURCE.replace('return *', 'return (index++, *'), ASM),
    (SOURCE, ASM.replace('%lo(table)', '%lo(other)')),
    (SOURCE, ASM.replace('lbu $a0', 'lb $a0')),
])
def test_requires_a_bounded_index_and_matching_target_dataflow(source, asm):
    assert masked_byte_stride_variants(source, 'lookup', 'mips', asm) == []
