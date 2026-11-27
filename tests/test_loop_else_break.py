"""A loop whose exit is the `else` of its test, so the compiler leaves the test at the top."""
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


def test_declines_what_would_change_meaning():
    stepped = 'void f(s32 n) {\n    s32 i;\n    for (i = 0; i < n; i++) {\n        if (a()) continue;\n        g();\n    }\n}\n'
    assert m.variants(stepped, 'f') == []
    goto = ('void f(void) {\n    s32 i;\n    switch (k) {\n    case 0:\nl:\n        if (c()) {\n            if (d()) break;\n'
            '            goto l;\n        }\n    }\n}\n')
    assert m.variants(goto, 'f') == []


def test_registered():
    assert any(r.module == 'loop_else_break' for r in registry.declared())
