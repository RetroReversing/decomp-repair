"""A loop whose exit is the `else` of its test, so the compiler leaves the test at the top."""
import re

from decomprepair import loop_else_break as m
from decomprepair import registry

# The shape of an 84-instruction option printer: m2c's two copies of one loop, one as `for (;;)`, one as a goto.
DRAFT = '''void f(s32 arg0, s32 arg1) {
    int flag;
    s32 var_s0;
    u32 temp_a3;

    var_s0 = 0;
    if (check(arg0) == 0) {
        for (;;) {
            temp_a3 = var_s0 & 0xFFFF;
            do { flag = temp_a3 < (u32) (arg1 & 0xFF); } while (0);
            if (flag) {
                show(arg0);
                var_s0 += 1;
                continue;
            }
            break;
        }
    } else {
loop_7:
        if ((u32) (arg1 & 0xFF) > (var_s0 & 0xFFFF)) {
            show(arg0);
            var_s0 += 1;
            goto loop_7;
        }
    }
}
'''


def test_both_loops_and_the_counter_into_the_arms():
    out = dict(m.variants(DRAFT, 'f'))
    arms = out['loop_else_break_arms']
    assert arms.count('while (1) {') == 2
    assert arms.count('} else {\n                break;') + arms.count('break;\n            }') >= 2
    assert arms.count('var_s0 = 0;') == 2
    assert 'goto' not in arms and 'loop_7' not in arms and 'continue' not in arms
    assert 'flag = temp_a3 < (u32) (arg1 & 0xFF);' in arms and 'do {' not in arms
    assert out['loop_else_break_all'].count('var_s0 = 0;') == 1


def test_for_and_leading_break():
    src = '''void f(s32 n) {
    s32 i;

    for (i = 0; i < n; i++) {
        g(i);
    }
    for (;;) {
        if (done()) break;
        h();
    }
    if (n)
        while (more()) step();
}
'''
    out = m.variants(src, 'f')
    every = dict(out)['loop_else_break_all']
    assert 'i = 0;\n    while (1) {\n        if (i < n) {' in every
    assert 'i++;\n        } else {\n            break;' in every
    assert 'if (!(done())) {' in every or 'if (!done()) {' in every
    assert 'if (more()) {' in every
    assert every.count('{') == every.count('}')


def test_goto_loop_with_statements_before_its_test():
    src = '''void f(s32 count) {
    s32 i;
    u32 low;

    i = 0;
loop_1:
    low = i & 0xFFFF;
    if (low < (u32) count) {
        show(name, low);
        i += 1;
        goto loop_1;
    }
    done();
}
'''
    out = dict(m.variants(src, 'f'))['loop_else_break']
    assert 'while (1) {\n        low = i & 0xFFFF;\n        if (low < (u32) count) {' in out
    assert 'i += 1;\n        } else {\n            break;\n        }\n    }\n    done();' in out
    assert 'goto' not in out and 'loop_1' not in out
    # a statement that is not plain (a test of its own, a label, a `break` that would bind to the new loop) keeps the goto
    for extra in ('if (a()) return;', 'break;', 'continue;', 'other:'):
        assert m.variants(src.replace('    low = i & 0xFFFF;', '    ' + extra + '\n    low = i & 0xFFFF;'), 'f') == []


def test_the_loop_and_its_symbol_base_together():
    src = '''void f(s32 count) {
    s32 i;
    u32 low;
    s32 *__base_D_80001000;

    i = 0;
    __base_D_80001000 = D_80001000;
loop_1:
    low = i & 0xFFFF;
    if (low < (u32) count) {
        show(__base_D_80001000, low);
        i += 1;
        goto loop_1;
    }
}
'''
    out = dict(m.variants(src, 'f'))
    both = out['loop_else_break_base']
    assert 'show(D_80001000, low);' in both and '__base' not in both
    assert 'while (1) {' in both and 'goto' not in both
    assert '__base_D_80001000' in out['loop_else_break']
    assert 'loop_else_break_base' not in dict(m.variants(DRAFT, 'f'))


def test_declines_what_would_change_meaning():
    goto = ('void f(void) {\n    s32 i;\n    switch (k) {\n    case 0:\nl:\n        if (c()) {\n            if (d()) break;\n'
            '            goto l;\n        }\n    }\n}\n')
    assert m.variants(goto, 'f') == []


def test_for_with_a_continue_keeps_its_step():
    src = '''void f(s32 n) {
    s32 i;
    s32 j;

    for (i = 0; i < n; i++) {
        if (skip(i)) {
            continue;
        }
        for (j = 0; j < n; j++) {
            if (j == i) continue;
            use(i, j);
        }
    }
}
'''
    every = dict(m.variants(src, 'f'))['loop_else_break_all']
    one = [text for family, text in m.variants(src, 'f') if family == 'loop_else_break'][0]
    # the outer loop's `continue` goes to a label ahead of the outer step; the inner loop keeps its own
    assert 'continue;' not in one.split('for (j = 0')[0]
    assert re.search(r'goto (repair_step_\d+);\n(.|\n)*\1:;\n\s*i\+\+;', one)
    assert 'if (j == i) continue;' in one
    assert every.count('i++;') == 1 and 'while (1) {' in every
    assert every.count('{') == every.count('}')


def test_a_goto_to_the_statement_after_the_loop_is_its_break():
    src = '''void f(s32 n) {
    s32 i;

    i = 0;
    for (;;) {
        if (i >= n) goto done;
        g(i);
        i += 1;
    }
done:
    h();
}
'''
    out = m.variants(src, 'f')[0][1]
    assert 'while (1) {\n        if (i < n) {' in out and 'goto done' not in out
    elsewhere = src.replace('done:\n    h();', 'h();\ndone:\n    k();')
    assert m.variants(elsewhere, 'f') == []


def test_registered():
    assert any(r.module == 'loop_else_break' for r in registry.declared())
