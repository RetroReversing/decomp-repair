"""The differences a float expression converts, named in float locals ahead of the statement."""
from decomprepair.float_difference_locals import FAMILY, variants

# A triangle winding test as m2c drafts it (SN64 GCC 2.8.1, N64).
WINDING = '''s32 f(void *a)
{
    s16 x0;
    s16 y0;

    x0 = *(s16 *) ((s8 *) a + 0);
    y0 = *(s16 *) ((s8 *) a + 2);
    if (!((((f32) (*(s16 *) ((s8 *) a + 4) - x0) * (f32) (*(s16 *) ((s8 *) a + 0xA) - y0)) - ((f32) (*(s16 *) ((s8 *) a + 6) - y0) * (f32) (*(s16 *) ((s8 *) a + 8) - x0))) < 0.0f)) {
        return 0;
    }
    return 1;
}
'''


def _children(text):
    return [src for fam, src in variants(text, 'f') if fam == FAMILY]


def test_the_x_differences_come_first_then_the_y_differences():
    child = _children(WINDING)[0]
    assert '''    repair_diff0 = *(s16 *) ((s8 *) a + 4) - x0;
    repair_diff1 = *(s16 *) ((s8 *) a + 8) - x0;
    repair_diff2 = *(s16 *) ((s8 *) a + 6) - y0;
    repair_diff3 = *(s16 *) ((s8 *) a + 0xA) - y0;
    if (!(((repair_diff0 * repair_diff3) - (repair_diff2 * repair_diff1)) < 0.0f)) {''' in child
    assert child.startswith('s32 f(void *a)\n{\n    f32 repair_diff0;\n    f32 repair_diff1;\n')


def test_the_written_order_is_offered_too_and_no_child_repeats():
    children = _children(WINDING)
    assert len(children) == len(set(children)) >= 3
    assert any('repair_diff1 = *(s16 *) ((s8 *) a + 0xA) - y0;' in child for child in children)


def test_a_repeated_difference_has_one_local():
    child = _children('f32 f(s32 a, s32 b, s32 c) {\n    return (f32) (a - c) * (f32) (a - c) + (f32) (b - c);\n}\n')[0]
    assert child.count(' - c;') == 2
    assert 'return repair_diff0 * repair_diff0 + repair_diff1;' in child


def test_calls_short_circuits_and_single_differences_are_left_alone():
    assert not _children('f32 f(s32 a, s32 b) {\n    return (f32) (a - b) * (f32) (g() - b);\n}\n')
    assert not _children('s32 f(s32 *p, s32 b) {\n    if (p && (f32) (*p - b) > (f32) (p[1] - b)) { return 1; }\n    return 0;\n}\n')
    assert not _children('f32 f(s32 a, s32 b) {\n    return (f32) (a - b) * 2.0f;\n}\n')
    assert not _children('f32 f(s32 a, s32 b, s32 c) {\n    if (c)\n        return (f32) (a - b) * (f32) (c - b);\n    return 0.0f;\n}\n')
    assert not _children('f32 f(s32 a, s32 b) {\n    f32 d = (f32) (a - b) * (f32) (b - a);\n    return d;\n}\n')
