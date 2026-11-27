from decomprepair import byte_index_shift as repair

HEADER = '''typedef unsigned char u8;
#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
'''
ASM = 'sll $v0, $v0, 4\n'
SOURCE = '''void f(char *p) {
    use((M2C_FIELD(p, u8 *, 4) * 0x10));
    use((M2C_FIELD(p, u8 *, 8) * 16));
}
'''


def test_offers_individual_and_combined_shifts():
    out = repair.variants(SOURCE, 'f', ASM, HEADER)
    assert len(out) == 3
    assert out[-1][1].count('<< 4') == 2


def test_requires_unsigned_byte_and_matching_shift():
    assert not repair.variants(SOURCE, 'f', ASM, HEADER.replace('unsigned char', 'signed char'))
    assert not repair.variants(SOURCE, 'f', ASM.replace(', 4', ', 5'), HEADER)
    assert not repair.variants(SOURCE, 'f', ASM, '')
