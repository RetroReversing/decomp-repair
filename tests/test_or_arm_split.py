"""`if (a || b) S` as two arms with the same body."""
from decomprepair.or_arm_split import variants

SOURCE = '''u8 f(void)
{
    if (b == 0 || b == 0x17) {
        r = 0;
    } else if (b == 1) {
        r = 1;
    } else if ((a || c) && d) {
        r = 2;
    }
    if (a || b || c) { g(); }
    return r;
}
'''


def _squash(text):
    return ' '.join(text.split())


def test_the_arm_is_written_once_per_test_and_the_else_stays_on_the_last():
    children = [_squash(t) for _, t in variants(SOURCE, 'f')]
    assert any('if (b == 0) { r = 0; } else if (b == 0x17) { r = 0; } else if (b == 1)' in t for t in children)
    assert any('if (a) { g(); } else if (b) { g(); } else if (c) { g(); }' in t for t in children)
    assert 'if (b == 0x17)' in children[0] and 'if (c) { g(); }' in children[0]


def test_an_or_inside_an_and_and_a_labelled_body_stay():
    assert variants('void f(void) { if ((a || c) && d) { g(); } if (a || b) { L: g(); } }', 'f') == []
