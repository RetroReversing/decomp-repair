"""m2c's `while (a || b)`, written back from the goto into the else arm."""
from decomprepair.goto_or_loop import FAMILY, variants

DRAFT = '''s32 f(s32 x, s32 y)
{
    s32 n;
    n = 0;
loop_2:
    if (x <= 0x10000) {
        if (y > 0x10000) {
            x = x >> 1;
            goto block_1;
        }
        return g(x + y) << n;
    } else {
        x = x >> 1;
block_1:
        y = y >> 1;
        n += 1;
        goto loop_2;
    }
}
'''


def _children(text):
    return [src for fam, src in variants(text, 'f') if fam == FAMILY]


def test_the_two_arms_become_one_while_loop():
    assert _children(DRAFT) == ['''s32 f(s32 x, s32 y)
{
    s32 n;
    n = 0;
    while (x > 0x10000 || y > 0x10000) {
        x = x >> 1;
        y = y >> 1;
        n += 1;
    }
    return g(x + y) << n;
}
''']


def test_arms_that_start_differently_are_left_alone():
    assert not _children(DRAFT.replace('        x = x >> 1;\nblock_1:', '        x = x >> 2;\nblock_1:'))


def test_a_label_with_another_goto_is_left_alone():
    assert not _children(DRAFT.replace('    n = 0;\n', '    n = 0;\n    if (y == 0) { goto block_1; }\n'))
