from decomprepair import symbol_row_arrays as rows

DRAFT = '''typedef int M2C_UNK;
extern M2C_UNK D_80100000;
extern M2C_UNK D_8010012C;
extern M2C_UNK D_80100400;

void f(s32 arg0, s32 arg1) {
    s32 var_a2;
    s32 var_v0;
    s32 n;

    var_a2 = 0;
    var_v0 = 0 * 2;
    do {
        *(s32 *)(var_v0 + (((arg1 & 0xFF) * 0x12C) + &D_80100000)) = 0;
        var_a2 += 1;
        var_v0 = var_a2 * 2;
    } while (var_a2 < 0x96);
    n = *(u32 *)((arg0 * 4) + (((arg1 & 0xFF) << 5) + &D_80100400));
    *(s32 *)((n * 2) + (&D_80100000 + 0x12C)) = 1;
    *(s32 *)((n * 2) + &D_8010012C) = *(s32 *)((arg0 * 2) + &D_8010012C);
    *(&D_80100000 + (n * 2)) = 2;
}
'''


def test_byte_arithmetic_tables_become_two_dimensional_arrays():
    unsigned, signed = rows.variants(DRAFT, 'f')
    out = unsigned[1]
    assert unsigned[0] == 'symbol_row_arrays'
    assert 'extern u16 D_80100000[][150];' in out and 'extern u32 D_80100400[][8];' in out
    assert 'D_80100000[arg1 & 0xFF][var_a2] = 0;' in out
    assert 'n = D_80100400[arg1 & 0xFF][arg0];' in out
    assert 'D_80100000[1][n] = 1;' in out
    assert 'D_80100000[1][n] = D_80100000[1][arg0];' in out
    assert 'D_80100000[0][n] = 2;' in out
    assert 'D_8010012C' not in out and 'var_v0' not in out
    assert 'extern s16 D_80100000[][150];' in signed[1]


def test_declines_a_symbol_used_another_way():
    source = '''extern int D_80100000;
void f(int r, int i) {
    *(&D_80100000 + ((r * 0x40) + (i * 4))) = 0;
    g(&D_80100000);
}
'''
    assert rows.variants(source, 'f') == []


def test_declines_one_scale_and_declared_symbols():
    source = '''extern int D_80100000;
void f(int i) {
    *(&D_80100000 + (i * 4)) = 0;
}
'''
    assert rows.variants(source, 'f') == []
    assert rows.variants(DRAFT, 'f', 'extern short D_80100000[]; extern int D_80100400[];') == []
