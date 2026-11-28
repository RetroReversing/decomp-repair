from decomprepair import float_compare_limit_weight as fw

ASM = 'mtc1 $zero, $f0\n c.lt.s $f2, $f0\n'
SOURCE = """\
extern f32 D_SCROLL;
void reset(s32);
void tick(s32 y)
{
    D_SCROLL -= 0.5;
    if ((f32) y < 0.0f) {
        reset(0);
    } else if (D_SCROLL > 1.0f) {
        reset(1);
    }
}
"""


def test_the_literal_is_set_in_a_two_deep_scope_before_the_test():
    family, text = fw.variants(SOURCE, 'tick', ASM)[0]
    assert family == 'float_compare_limit_weight'
    assert '    float limit;' in text
    assert 'do { do { limit = 0.0f; } while (0); } while (0);\n    if ((f32) y < limit) {' in text
    assert 'D_SCROLL > 1.0f' in text  # an `else if` is left alone


def test_depths_one_and_three_follow_and_the_gate_holds():
    texts = [t for _, t in fw.variants(SOURCE, 'tick', ASM)]
    assert len(texts) == 3
    assert 'do { limit = 0.0f; } while (0);\n    if' in texts[1]
    assert 'do { do { do { limit = 0.0f; } while (0); } while (0); } while (0);' in texts[2]
    assert fw.variants(SOURCE, 'tick', 'slt $v0, $s1, $zero\n') == []


def test_a_literal_on_the_left_and_a_double_literal():
    left = SOURCE.replace('(f32) y < 0.0f', '0.0f > (f32) y')
    assert 'if (limit > (f32) y) {' in fw.variants(left, 'tick', ASM)[0][1]
    assert fw.variants(SOURCE.replace('< 0.0f', '< 0.0'), 'tick', ASM) == []
