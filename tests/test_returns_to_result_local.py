"""Leaf returns of an `if` tree through one result local."""
from decomprepair.returns_to_result_local import variants

SOURCE = '''u8 f(void)
{
    if (a == 5) {
        if (b == 0) {
            return 0;
        } else if (b == 1) {
            return 1;
        } else {
            return b == 2 ? 2 : 3;
        }
    } else {
        return g();
    }
}
'''


def _squash(text):
    return ' '.join(text.split())


def test_every_leaf_assigns_and_the_function_returns_once():
    (_, child), = variants(SOURCE, 'f')
    text = _squash(child)
    assert text.startswith('u8 f(void) { u8 __repair_result; if (a == 5)')
    assert text.count('return') == 1 and text.endswith('__repair_result = g(); } return __repair_result; }')
    assert '__repair_result = b == 2 ? 2 : 3;' in text


def test_a_path_that_does_not_return_or_an_early_return_stays():
    assert variants('s32 f(void) { if (a) { return 1; } if (b) { return 2; } return 3; }', 'f') == []
    assert variants('s32 f(void) { if (a) { return 1; } else if (b) { return 2; } else if (c) { return 3; } }', 'f') == []
    assert variants('void f(void) { if (a) { return; } else if (b) { return; } else { return; } }', 'f') == []
