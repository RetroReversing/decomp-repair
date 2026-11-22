"""A loop statement written as a backward goto, which gcc 2.7.2's loop pass leaves alone."""
from decomprepair import loop_goto_form_repairs as g

DO_WHILE = '''void f(s32 *cur, s32 n) {
    s32 *p = cur;
    do {
        if (n > 4) {
            break;
        }
        p[0] = 0xDA380003;
        p += 2;
    } while (--n != 0);
    h(p);
}
'''

FOR = '''void f(s32 *p, s32 n) {
    s32 i;
    for (i = 0; i < n; i++) {
        p[i] = 0xDA380003;
    }
}
'''


def test_do_while_becomes_goto_loop_with_break_target():
    (family, text), = g.variants(DO_WHILE, 'f')
    assert family == 'loop_goto_form' == g.FAMILY
    assert 'do {' not in text and 'while' not in text
    assert 'loop_goto_1:' in text and 'goto loop_goto_1;' in text
    assert 'goto loop_goto_end_1;' in text and 'loop_goto_end_1:;' in text
    assert 'if (--n != 0)' in text


def test_for_loop_keeps_init_and_step():
    (family, text), = g.variants(FOR, 'f')
    assert 'for' not in text
    assert 'i = 0;' in text and 'loop_goto_1:' in text and 'if (i < n)' in text
    assert text.index('p[i] = 0xDA380003;') < text.index('i++;') < text.index('goto loop_goto_1;')


def test_continue_and_labels_are_left_alone():
    assert g.variants(DO_WHILE.replace('break;', 'continue;'), 'f') == []
    assert g.variants(DO_WHILE.replace('p += 2;', 'again:\n        p += 2;'), 'f') == []


def test_nested_break_belongs_to_the_inner_switch():
    source = '''void f(s32 n) {
    do {
        switch (n) {
        case 1:
            n = 2;
            break;
        }
    } while (--n);
}
'''
    (family, text), = g.variants(source, 'f')
    assert 'loop_goto_end' not in text and 'break;' in text


def test_no_loop_no_variant():
    assert g.variants('void f(void) { h(); }', 'f') == []
