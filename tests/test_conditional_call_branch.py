from decomprepair.conditional_call_branch import variants

SOURCE = '''
void f(int cond, int value) {
    if (cond) value = 64;
    do { do { call(value, 1); } while (0); } while (0);
    later(value);
}
'''


def test_keeps_the_assignment_before_the_call_and_later_use():
    children = variants(SOURCE, 'f')
    assert len(children) == 1
    text = children[0][1]
    assert 'if (cond == 0)' in text
    assert text.count('call(value, 1);') == 2
    assert 'value = 64;' in text and 'later(value);' in text
    assert 'while (0)' not in text


def test_rejects_dangling_control_and_opaque_call_macros():
    assert not variants(SOURCE.replace('if (cond)', 'if (outer) if (cond)'), 'f')
    assert not variants(SOURCE, 'f', '#define call(x, y) other(x, y)')
    assert not variants(SOURCE, 'f', '#define value dynamic_lvalue()')
    assert not variants(SOURCE + '\nint line = __LINE__;', 'f')
    assert not variants(SOURCE.replace('call(value, 1);', 'call(value, __LINE__);'), 'f')
    assert not variants(SOURCE.replace('call(value, 1);', 'call(value, 1); extra();'), 'f')


def test_requires_a_plain_integer_condition():
    assert not variants(SOURCE.replace('int cond', 'Unknown cond'), 'f')
    assert not variants(SOURCE.replace('int cond', 'int *cond'), 'f')
    assert not variants(SOURCE.replace('int cond', 'u8 cond'), 'f')
    assert variants(SOURCE.replace('int cond', 'u8 cond'), 'f', 'typedef unsigned char u8;')
