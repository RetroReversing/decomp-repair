from decomprepair import fill_extent_locals as repair

DRAFT = '''
void f(void) {
    f32 sp20;
    s32 sp30;
    s32 sp34;
    f32 sp38;

    memSet(&sp20, 0, 0xCU);
    sp20 = 20.0f;
    memSet(&sp30, 0, 0xCU);
    g(sp30, sp34, sp38, sp20);
}
'''


def _children(source):
    return [child for family, child in repair.variants(source, 'f') if family == 'fill_extent_scalar']


def test_filled_scalars_become_arrays_of_the_fill_length():
    child = _children(DRAFT)[0]
    assert 'f32 sp20[3];' in child and 's32 sp30[3];' in child
    assert 'sp34;' not in child and 'f32 sp38;' not in child
    assert 'memSet(sp20, 0, 0xCU);' in child and 'sp20[0] = 20.0f;' in child
    assert 'g(sp30[0], sp30[1], (*(f32 *)&sp30[2]), sp20[0]);' in child


def test_each_filled_scalar_is_offered_alone_too():
    assert len(_children(DRAFT)) == 3


def test_a_fill_of_one_element_is_left_alone():
    assert not _children('void f(void) {\n    s32 sp20;\n\n    memSet(&sp20, 0, 4);\n    g(sp20);\n}\n')


def test_a_bitwise_and_is_not_an_address():
    source = 'void f(s32 a) {\n    s32 sp20;\n\n    memSet(&sp20, 0, 8);\n    g(a & sp20, &sp20);\n}\n'
    assert 'g(a & sp20[0], sp20);' in _children(source)[0]
