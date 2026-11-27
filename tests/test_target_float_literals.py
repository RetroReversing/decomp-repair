from decomprepair import registry
from decomprepair import target_float_literals as family

ASM = """
    lui $at, (0x42340000 >> 16)
    mtc1 $at, $f2
    mul.s $f0, $f0, $f2
    lui $at, (0x40800000 >> 16)
    mtc1 $at, $f4
    add.s $f0, $f0, $f4
    lui $at, (0x40490FDB >> 16)
    ori $at, $at, (0x40490FDB & 0xFFFF)
    mtc1 $at, $f22
    lui $at, 0x4334
    mtc1 $at, $f20
    mul.s $f12, $f12, $f22
    div.s $f12, $f12, $f20
"""

SOURCE = """extern f32 D_1[8];
void func_1(void)
{
    s32 i;
    for (i = 0; i < 8; i++) { D_1[i] = i * 45; }
    for (i = 0; i < 8; i++) { D_1[i] = D_1[i] + 4.0; }
    for (i = 0; i < 8; i++) { D_1[i] = __sinf((f32)(D_1[i] * 3.14 / 180.0)); }
}
"""


def test_literals_become_the_target_words():
    floats, both = [text for _, text in family.variants(SOURCE, 'func_1', ASM)]
    assert 'D_1[i] + 4.0f;' in floats
    assert '* 3.1415927f / 180.0f' in floats
    assert 'i * 45;' in floats
    assert 'i * 45.0f;' in both and '3.1415927f / 180.0f' in both
    assert 'i < 8' in both and 'D_1[8]' in both


def test_index_factors_and_unbuilt_constants_stay():
    source = 'void func_1(void)\n{\n    D_1[2 * 45] = x * 0.5 + 7;\n}\n'
    assert family.variants(source, 'func_1', ASM) == []


def test_needs_single_precision_arithmetic():
    assert family.variants(SOURCE, 'func_1', ASM.replace('.s ', '.d ')) == []


def test_declared():
    assert family.FAMILY in {name for one in registry._modules() for name in one.families}
