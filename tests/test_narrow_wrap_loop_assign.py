"""An `s16` angle's wrap loop with its `u16` twin assigned in the test (an N64 turning routine, 620 -> 0)."""
from decomprepair.narrow_wrap_loop_assign import FAMILY, variants

SOURCE = """s32 turn(s32 offset, s32 dx, s32 dy)
{
    s16 angle;

    angle = offset + (direction(dx, dy) + 0xC00);
    while (angle < 0) {
        angle += 0x1000;
    }
    return angle;
}
"""


def test_twin_is_assigned_in_the_test():
    children = variants(SOURCE, 'turn')
    assert [family for family, _ in children] == [FAMILY, FAMILY]
    first = children[0][1]
    assert 'u16 wrap_angle;' in first
    assert 'wrap_angle = offset + (direction(dx, dy) + 0xC00);' in first
    assert 'while ((angle = wrap_angle) < 0) {' in first
    assert 'wrap_angle = angle + 0x1000;' in first
    assert 'wrap_angle += 0x1000;' in children[1][1]


def test_goto_form_and_unbraced_step():
    goto = SOURCE.replace('while (angle < 0) {\n        angle += 0x1000;\n    }',
                          'loop_1:\n    if (angle < 0) {\n        angle += 0x1000;\n        goto loop_1;\n    }')
    assert 'while ((angle = wrap_angle) < 0)' in variants(goto, 'turn')[0][1]
    bare = SOURCE.replace('while (angle < 0) {\n        angle += 0x1000;\n    }', 'while (angle >= 0x1000)\n'
                          '        angle = angle - 0x1000;')
    assert 'wrap_angle = angle - 0x1000;' in variants(bare, 'turn')[0][1]


def test_left_alone_when_wide_or_conditionally_set():
    assert not variants(SOURCE.replace('s16 angle;', 's32 angle;'), 'turn')
    guarded = SOURCE.replace('    angle = offset', '    if (dx) angle = offset')
    assert not variants(guarded, 'turn')
