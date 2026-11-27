from decomprepair import registry
from decomprepair.result_constant_returns import FAMILY, variants

SOURCE = """s32 f(s32 a, s32 b) {
    s32 var_v0;
    s32 t;

    var_v0 = 0;
    if (a != 0) {
        var_v0 = 0;
        if (b == 2) {
            return h();
        }
        t = g();
        if (t & 0x9000) {
            k();
            var_v0 = 1;
        }
        return var_v0;
    }
    return var_v0;
}
"""


def _kid(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_each_decided_constant_is_returned_where_it_is_decided():
    [kid] = _kid()
    assert 'k();\n            var_v0 = 1;\n         return 1; }' in kid
    assert kid.count('return 0;') == 2
    assert 'return var_v0;' not in kid


def test_a_value_that_depends_on_a_call_is_left():
    [kid] = _kid(SOURCE.replace('var_v0 = 1;', 'var_v0 = g();'))
    assert 'return var_v0;' in kid and 'return 1;' not in kid


def test_a_loop_is_left_alone():
    assert not _kid(SOURCE.replace('t = g();', 'while (g()) { }'))


def test_the_module_is_registered():
    assert registry.problems(registry.get('result_constant_returns')) == []
