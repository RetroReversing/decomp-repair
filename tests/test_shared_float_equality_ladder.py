from decomprepair import shared_float_equality_ladder as repair

ASM = '''c.eq.s $f2, $f0
nop
bc1tl .Lshared
nop
c.eq.s $f2, $f0
nop
nop
bc1tl .Lshared
nop
'''
SOURCE = '''void f(void) {
    f32 x;
    if (x == 1.0f) {
        shared();
    } else if (x == -1.0f) {
        shared();
    } else {
        normal();
    }
    after();
}
'''


def test_identical_arms_become_two_branches_to_one_shared_copy():
    out = repair.variants(SOURCE, 'f', ASM)
    assert len(out) == 1
    text = out[0][1]
    assert 'if (x == 1.0f) goto shared_arm_0;' in text
    assert 'if (x == -1.0f) goto shared_arm_0;' in text
    assert text.count('shared();') == 1 and text.index('normal();') < text.index('shared_arm_0:')
    assert 'shared_done_0:;' in text and 'after();' in text


def test_rejects_different_bodies_volatile_values_and_hidden_macros():
    assert repair.variants(SOURCE, 'f', ASM.replace('.Lshared', '.Ldifferent', 1)) == []
    assert repair.variants(SOURCE.replace('shared();', 'different();', 1), 'f', ASM) == []
    assert repair.variants(SOURCE.replace('f32 x;', 'volatile f32 x;'), 'f', ASM) == []
    assert repair.variants(SOURCE, 'f', ASM, '#define shared() __LINE__') == []
    assert repair.variants(SOURCE, 'f', ASM, '#define normal() __LINE__') == []
    assert repair.variants(SOURCE.replace('normal();', 'use(__LINE__);'), 'f', ASM) == []
    assert repair.variants(SOURCE.replace('shared();', 'use(__LINE__);'), 'f', ASM) == []
    assert repair.variants(SOURCE.replace('normal();', 'goto elsewhere;'), 'f', ASM) == []


def test_generated_labels_avoid_header_macro_names():
    out = repair.variants(SOURCE, 'f', ASM, '#define shared_arm_0 other')
    assert out and 'goto shared_arm_1;' in out[0][1]
