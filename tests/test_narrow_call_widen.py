from decomprepair.narrow_call_widen import variants

SOURCE = '''
s32 f(void *p) {
    s16 x;
    x = get(p, 2);
    use(x);
    return x;
}
'''


def test_explicitly_narrows_the_call_before_widening():
    children = variants(SOURCE, 'f')
    assert len(children) == 1
    assert 's32 x;' in children[0][1]
    assert 'x = (s16) get(p, 2);' in children[0][1]


def test_avoids_address_type_checks_and_later_writes():
    for extra in ('use(&x);', 'use(sizeof(x));', 'use(sizeof((x)));', 'x += 1;', 'x <<= 1;', 'x = other();', 'x++;', 'use(&(x));', 'use(&((x)));'):
        assert variants(SOURCE.replace('    return x;', '    ' + extra + '\n    return x;'), 'f') == []


def test_does_not_rewrite_plain_arithmetic_assignment():
    assert not variants(SOURCE.replace('get(p, 2)', '1 + 2'), 'f')
