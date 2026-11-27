"""A symbol the target holds in a saved register, read through a pointer local set at the top."""
from decomprepair.held_symbol_pointer import FAMILY, variants

SOURCE = '''typedef struct { u16 sel; u8 f[4]; } Sel;
extern Sel D_1;
extern s16 D_2[];
extern s16 D_3[];
void f(void) {
    s32 i;
    use(D_1.sel, D_1.f[D_1.sel]);
    D_2[1] = D_3[0];
    call(D_2);
}
'''
ASM = '''  lui $s6, %hi(D_1)
  addiu $s6, $s6, %lo(D_1)
  lui $s7, %hi(D_2)
  addiu $s7, $s7, %lo(D_2)
  lui $a0, %hi(D_3)
  addiu $a0, $a0, %lo(D_3)
'''


def test_held_symbols_are_read_through_pointers():
    children = variants(SOURCE, 'f', ASM)
    assert [family for family, _ in children] == [FAMILY] * 3
    together = children[-1][1]
    assert 'Sel *held_D_1 = &D_1;\n    s16 *held_D_2 = D_2;\n    s32 i;' in together
    assert 'use(held_D_1->sel, held_D_1->f[held_D_1->sel]);' in together
    assert 'held_D_2[1] = D_3[0];' in together and 'call(held_D_2);' in together
    assert 'extern Sel D_1;' in together


def test_without_a_saved_register_nothing_is_offered():
    assert variants(SOURCE, 'f', ASM.replace('$s', '$a')) == []
    assert variants(SOURCE, 'f') == []


def test_an_address_built_after_a_call_is_not_offered():
    assert variants(SOURCE, 'f', '  jal func_1\n' + ASM) == []
