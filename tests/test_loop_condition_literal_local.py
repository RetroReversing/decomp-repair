from decomprepair.loop_condition_literal_local import variants

SOURCE = '''typedef unsigned short u16;
void f(u16 *list, int i)
{
    int j;

    for (;;) {
        j = i;
        do {
            if (list[j] != list[i]) {
                goto found;
            }
            j++;
        } while (list[j] != 0xFFFF);
    found:
        i = j;
    }
}
'''


def children(source, name='f'):
    return [child for _, child in variants(source, name)]


def test_the_literal_is_set_before_its_loop():
    narrow, wide = children(SOURCE)
    for child, kind in ((narrow, 'u16'), (wide, 's32')):
        assert f'{kind} loop_literal0;' in child
        assert 'loop_literal0 = 0xFFFF;\n    do {' in child
        assert 'while (list[j] != loop_literal0);' in child


def test_a_while_loop_and_a_negative_literal():
    child = children('void f(int *p)\n{\n    while (*p != -1) {\n        p++;\n    }\n}\n')[-1]
    assert 'loop_literal0 = -1;\n    while (*p != loop_literal0)' in child


def test_zero_and_an_unbraced_body_are_left_alone():
    assert children('void f(int *p)\n{\n    while (*p != 0) {\n        p++;\n    }\n}\n') == []
    assert children('void f(int *p, int c)\n{\n    if (c)\n        while (*p != 5)\n            p++;\n}\n') == []
