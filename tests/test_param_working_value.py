from decomprepair import param_working_value as repairs

COPY = '''void f(unsigned int *out, unsigned char width, s16 value) {
    s32 num;
    s32 low;
    num = value;
    if (value < 0) {
        value = value;
    }
    low = 5 - width;
}
'''

SOURCE = '''void f(unsigned int *out, u8 width, s16 value) {
    u8 buf[7];
    s32 num;
    s32 lim;
    num = value;
    if (value < 0) {
        num = -value;
    }
    buf[1] = (s16) num / 10;
    num = num - 3;
    lim = 5 - width;
    buf[lim] = 0x2D;
}
'''

READ = '''void f(s16 value) {
    u8 buf[7];
    s32 v;
    s32 rem;
    s32 pos;
    v = (s16) value;
    if (v < 0) {
        pos = 0;
        rem = -v;
    } else {
        pos = 1;
        rem = v;
    }
    buf[0] = rem / 10 + pos;
}
'''


def children(source):
    return dict(repairs.variants(source, 'f'))


def test_the_parameter_becomes_the_working_value_and_the_subtraction_is_staged_in_one_child():
    both = children(SOURCE)['param_works_split']
    assert 'num = value;\n    if (value < 0) {\n        value = -num;' in both
    assert 'buf[1] = (s16) value / 10;\n    value = value - 3;' in both
    assert 'lim = 5;\n    lim -= width;' in both


def test_each_edit_is_also_offered_alone():
    found = children(SOURCE)
    assert 'lim = 5 - width;' in found['param_works'] and 'value = -num;' in found['param_works']
    assert 'num = -value;' in found['constant_minus_split'] and 'lim -= width;' in found['constant_minus_split']


def test_a_copy_read_back_into_a_second_local_moves_to_the_parameter():
    child = children(READ)['param_works']
    assert 'v = value;\n    if ((s16) value < 0) {' in child and 'value = -v;' in child
    assert 'rem' not in child and 'buf[0] = value / 10 + pos;' in child


def test_a_parameter_the_function_reads_elsewhere_or_a_wide_one_is_left_alone():
    assert 'param_works' not in children(SOURCE.replace('buf[lim] = 0x2D;', 'buf[lim] = value;'))
    assert 'param_works' not in children(SOURCE.replace('s16 value', 's32 value'))
    assert 'param_works' not in children(COPY)  # the negation is not assigned to the local
