from decomprepair.index_2d_flatten import variants

SOURCE = '''extern u16 D_80000000[][24];
void f(s32 r, s32 c) {
    if (D_80000000[r][c] != 0xFFFF) {
        D_80000000[r + 1][c] = 0;
    }
}
'''


def test_both_operand_orders():
    first, second = [text for _, text in variants(SOURCE, 'f')]
    assert 'extern u16 D_80000000[];' in first and '[][24]' not in first
    assert 'D_80000000[c + r * 24] != 0xFFFF' in first and 'D_80000000[c + (r + 1) * 24] = 0;' in first
    assert 'D_80000000[r * 24 + c] != 0xFFFF' in second


def test_a_row_passed_whole_declines():
    assert variants('extern u8 T[][4];\nvoid f(s32 i) {\n    g(T[i]);\n}\n', 'f') == []
