from decomprepair.named_sum_difference import variants

SOURCE = '''int spread(void);
void f(int *out) {
    short angle;
    angle = spread();
    out[0] = (angle + 0x200) - (spread() >> 5);
}
'''


def test_the_sum_is_named_inside_the_expression():
    [(family, child)] = variants(SOURCE, 'f')
    assert family == 'named_sum_difference'
    assert 'out[0] = (named_sum = angle + 0x200) - (spread() >> 5);' in child
    assert '{\n    int named_sum;\n' in child
    assert variants(child, 'f') == []


def test_a_sum_on_the_right_and_an_unsigned_local():
    source = 'int g(void);\nint x;\nvoid f(u32 a) { x = g() - (a + 4); }\n'
    [(_, child)] = variants(source, 'f')
    assert 'unsigned int named_sum;' in child
    assert 'g() - (named_sum = a + 4)' in child


def test_constants_calls_conditions_and_unknown_types_are_left_alone():
    for line in ('x = (a + 4) - 2;', 'x = g(a + 4) - x;', 'x = (a + 4) * x;', 'x = (p + 4) - x;', 'if (a + 4) x = 1;'):
        assert variants('int x;\nchar *p;\nvoid f(int a) { %s }\n' % line, 'f') == [], line
