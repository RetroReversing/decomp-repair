from decomprepair import stored_stack_run as repair

DRAFT = '''
void f(f32 x, f32 y) {
    f32 sp40;
    f32 sp44;
    f32 sp48;
    f32 a;
    f32 b;

    a = x / 2.0f;
    sp40 = a;
    sp48 = -15000.0f;
    b = y / 2.0f;
    sp44 = b;
    g(1, a, b, -15000.0f);
}
'''


def test_stored_words_passed_on_become_one_array_read_back():
    family, child = repair.variants(DRAFT, 'f')[0]
    assert family == 'stored_stack_run'
    assert 'f32 sp40[3];' in child and 'f32 sp44;' not in child
    assert 'sp40[0] = a;' in child and 'sp40[1] = b;' in child and 'sp40[2] = -15000.0f;' in child
    assert 'g(1, sp40[0], sp40[1], sp40[2]);' in child


def test_a_value_changed_before_the_call_is_not_read_back():
    assert not repair.variants(DRAFT.replace('    g(1,', '    a = y;\n    g(1,'), 'f')


def test_a_call_in_between_stops_the_rewrite():
    assert not repair.variants(DRAFT.replace('    g(1,', '    h();\n    g(1,'), 'f')


def test_a_word_read_elsewhere_is_not_part_of_the_run():
    assert not repair.variants(DRAFT.replace('-15000.0f);\n}', '-15000.0f);\n    h(sp40, sp44, sp48);\n}'), 'f')



def test_the_family_is_declared():
    assert repair.REPAIR['families'] == ('stored_stack_run',)
