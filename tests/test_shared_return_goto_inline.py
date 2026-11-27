from decomprepair import registry
from decomprepair.shared_return_goto_inline import FAMILY, variants

SOURCE = """s32 f(s32 a, s32 b) {
    if (a == 0) {
        if (g(b) != 0) {
            __shared_return_0:
            return 0;
        }
        return h(b) == 0;
    }
    goto __shared_return_0;
}
"""


def _kids(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_a_goto_to_a_literal_return_becomes_that_return():
    [kid] = _kids()
    assert 'goto' not in kid and '__shared_return_0' not in kid
    assert kid.count('return 0;') == 2


def test_a_label_on_a_variable_return_is_left():
    assert not _kids(SOURCE.replace('return 0;', 'return a;'))


def test_the_module_is_registered():
    assert registry.problems(registry.get('shared_return_goto_inline')) == []
