"""The caller's own parameter passed on to a callee m2c gave one argument too few."""
from decomprepair import passthrough_argument_repairs as p

SOURCE = '''s32 g();
s32 h(s32, s32);

s32 f(s32 arg0, void *arg1, s32 arg2) {
    if (D != NULL) {
        g(arg0, D, M2C_FIELD(arg1, s32 *, 0xC), M2C_FIELD(arg1, s32 *, 0x24));
        return 1;
    }
    h(arg0, arg2);
    return 0;
}
'''


def test_each_parameter_at_its_own_position():
    # An N64 function at 95%: the game called g(arg0, D, arg2, ...), its $a2 untouched; exact so.
    calls = [text[text.index('        g('):text.index(';', text.index('        g('))] for _, text in p.variants(SOURCE, 'f')]
    assert '        g(arg0, D, arg2, M2C_FIELD(arg1, s32 *, 0xC), M2C_FIELD(arg1, s32 *, 0x24))' in calls
    assert '        g(arg0, arg1, D, M2C_FIELD(arg1, s32 *, 0xC), M2C_FIELD(arg1, s32 *, 0x24))' in calls


def test_a_prototype_is_widened_with_the_call():
    texts = [t for _, t in p.variants(SOURCE.replace('s32 g();', 's32 g(s32, void *, s32, s32);'), 'f')]
    assert any('s32 g(s32, void *, s32, s32, s32);' in t and 'g(arg0, D, arg2, M2C_FIELD' in t for t in texts)
    assert all(t.count('g(') == 2 for t in texts)  # the prototype and the one call


def test_a_prototyped_callee_gains_the_parameter():
    # Three N64 functions called f32 g(u16 *) as g(arg0, &sp10): exact with the prototype widened.
    source = 'f32 g(u16 *);\nvoid f(s32 arg0) {\n    u16 sp10;\n\n    h(g(&sp10), arg0);\n}\n'
    texts = [t for _, t in p.variants(source, 'f')]
    assert any('f32 g(s32, u16 *);' in t and 'g(arg0, &sp10)' in t for t in texts)
    twice = source.replace('h(g(&sp10), arg0);', 'h(g(&sp10), g(&sp10));')
    assert not any('f32 g(s32, u16 *);' in t for _, t in p.variants(twice, 'f'))


def test_a_callee_given_no_arguments_gets_all_of_the_callers_at_once():
    # (an N64 function: `f()` 40 points off, exact as `f(arg0, arg1, arg2)`)
    source = ('s32 func_8007A974();\n'
              's32 func_8007AA40(void *arg0, s32 arg1, s32 *arg2) {\n'
              '    func_8007A974();\n'
              '    return *arg2;\n'
              '}\n')
    texts = [t for _, t in p.variants(source, 'func_8007AA40')]
    assert any('func_8007A974(arg0, arg1, arg2);' in t for t in texts)
