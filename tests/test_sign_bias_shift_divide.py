from decomprepair.sign_bias_shift_divide import FAMILY, variants

SOURCE = '''extern u32 D_1;
extern s32 D_2;
void f(void) {
    g(D_3 + 0x2980, (s32) (D_1 + ((u32) D_1 >> 0x1F)) >> 1, 0x20, &h);
}
'''


def children(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_the_sign_bias_shift_becomes_the_signed_division():
    (child,) = children()
    assert 'g(D_3 + 0x2980, (s32) D_1 / 2, 0x20, &h);' in child


def test_other_order_spelling_and_shift_width():
    src = SOURCE.replace('(s32) (D_1 + ((u32) D_1 >> 0x1F)) >> 1', '(s32) (((unsigned) D_1 >> 31) + D_1) >> 4')
    (child,) = children(src)
    assert '(s32) D_1 / 16,' in child


def test_without_an_outer_signed_cast_the_quotient_has_the_operand_type():
    (child,) = children(SOURCE.replace('(s32) (D_1', '(D_1'))
    assert ', D_1 / 2,' in child


def test_each_site_and_all_together():
    two = SOURCE.replace('}\n', '    g(0, (s32) (D_2 + ((u32) D_2 >> 0x1F)) >> 3, 0, 0);\n}\n')
    texts = children(two)
    assert len(texts) == 3
    assert texts[-1].count(' / ') == 2


def test_different_operands_or_a_tighter_neighbour_are_left_alone():
    assert not children(SOURCE.replace('>> 0x1F', '>> 0x1E'))
    assert not children(SOURCE.replace('((u32) D_1 >>', '((u32) D_2 >>'))
    assert not children(SOURCE.replace(', (s32) (D_1', ', 3 + (s32) (D_1'))
    assert not children(SOURCE.replace(' >> 1,', ' >> 1 + 2,'))
