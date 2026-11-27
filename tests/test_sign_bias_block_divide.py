from decomprepair.sign_bias_block_divide import FAMILY, variants

SOURCE = '''s32 g(void *, s32, s32, s32);
void f(void *arg0) {
    s32 var_a1;
    s32 var_a2;
    s32 var_a3;
    var_a1 = (*(s32 *)((s8 *)arg0 + 0));
    if (var_a1 < 0) {
        var_a1 += 0xFF;
    }
    var_a2 = (*(s32 *)((s8 *)arg0 + 4));
    if (var_a2 < 0) {
        var_a2 += 0xFF;
    }
    var_a3 = (*(s32 *)((s8 *)arg0 + 8));
    g(&D_1, var_a1 >> 8, var_a2 >> 8, var_a3 / 0x100);
}
'''


def children(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_the_division_moves_to_each_load_and_the_shifts_go():
    texts = children()
    at_load = texts[2]
    assert 'var_a1 = (*(s32 *)((s8 *)arg0 + 0)) / 0x100;' in at_load
    assert 'var_a2 = (*(s32 *)((s8 *)arg0 + 4)) / 0x100;' in at_load
    assert 'g(&D_1, var_a1, var_a2, var_a3 / 0x100);' in at_load
    assert '+= 0xFF' not in at_load


def test_the_division_at_the_use_is_the_other_spelling():
    at_use = children()[-1]
    assert 'g(&D_1, var_a1 / 0x100, var_a2 / 0x100, var_a3 / 0x100);' in at_use
    assert 'var_a1 = (*(s32 *)((s8 *)arg0 + 0));' in at_use


def test_one_child_per_site_and_spelling_and_one_with_all():
    assert len(children()) == 6
    assert len(children(SOURCE.replace('    var_a2 = (*(s32 *)((s8 *)arg0 + 4));\n    if (var_a2 < 0) {\n'
                                       '        var_a2 += 0xFF;\n    }\n', '    var_a2 = 1;\n'))) == 2


def test_braceless_block_and_other_widths():
    src = '''void f(int x) {
    int v;
    v = x + 3;
    if (v < 0) v += 7;
    h(v >> 3);
}
'''
    assert 'v = (x + 3) / 8;' in children(src)[0]
    assert 'h(v / 8);' in children(src)[1]


def test_other_uses_or_wrong_constants_are_left_alone():
    one = SOURCE.replace('var_a2 >> 8', 'var_a2')
    assert children(one)
    assert not children(one.replace('var_a1 >> 8,', 'var_a1 >> 8 + var_a1,'))
    assert not children(one.replace('var_a1 >> 8,', 'var_a1,'))
    assert not children(one.replace('var_a1 += 0xFF', 'var_a1 += 0x7F'))
    assert not children(one.replace('s32 var_a1;', 'u32 var_a1;'))
    assert not children(one.replace(', var_a1 >> 8', ', 1 + var_a1 >> 8'))
    assert not children(one.replace(', var_a1 >> 8', ', var_a1 >> 8 >> 1'))
