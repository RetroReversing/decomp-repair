"""A float constant local split into one twin per call-argument position (a split-screen setup routine, 14156 -> 4500)."""
from decomprepair.float_role_twins import FAMILY, variants

SOURCE = """void setup(void)
{
    f32 cx = 160.0f;
    f32 cy = 120.0f;
    f32 half;
    s32 i;

    place(obj, cx, cy, 320.0f, 240.0f, 0.0f, 0.0f);
    for (i = 0; i < n; i++) {
        place(table[i], cx, cy, cx + cx, cy + cy, 0.0f, 0.0f);
    }
    half = cx * 0.5f;
    place(table[0], half, cy, cx, cy + cy, 1.0f, 1.0f);
}
"""


def children(source, name='setup'):
    return [text for family, text in variants(source, name) if family == FAMILY]


def test_every_local_gets_a_twin_per_argument_position_in_one_child():
    first = children(SOURCE)[0]
    assert 'f32 cx_r1 = 160.0f;\n    f32 cy_r2 = 120.0f;\n    f32 cx_r3 = 160.0f;\n    f32 cy_r4 = 120.0f;\n' in first
    assert 'f32 cx = 160.0f;' not in first and 'f32 cy = 120.0f;' not in first
    assert 'place(obj, cx_r1, cy_r2, 320.0f, 240.0f, 0.0f, 0.0f);' in first
    # a sum or a product inside an argument names that argument's twin
    assert 'place(table[i], cx_r1, cy_r2, cx_r3 + cx_r3, cy_r4 + cy_r4, 0.0f, 0.0f);' in first
    assert 'place(table[0], half, cy_r2, cx_r3, cy_r4 + cy_r4, 1.0f, 1.0f);' in first


def test_reads_outside_a_call_go_to_the_lowest_or_the_highest_position():
    low, high = children(SOURCE)[:2]
    assert 'half = cx_r1 * 0.5f;' in low
    assert 'half = cx_r3 * 0.5f;' in high


def test_each_local_alone_is_offered_too():
    alone = [text for text in children(SOURCE) if 'f32 cy = 120.0f;' in text]
    assert len(alone) == 1 and 'f32 cx_r1 = 160.0f;' in alone[0] and 'cy_r2' not in alone[0]


def test_a_local_read_at_one_position_only_is_left_alone():
    source = SOURCE.replace('place(obj, cx, cy, 320.0f, 240.0f, 0.0f, 0.0f);', 'place(obj, 1.0f, cy, 320.0f, 240.0f, 0.0f, 0.0f);')
    source = source.replace('cx + cx', '1.0f').replace('place(table[0], half, cy, cx,', 'place(table[0], half, cy, 1.0f,')
    source = source.replace('half = cx * 0.5f;', 'half = 1.0f;')
    for text in children(source):
        assert 'cx_r' not in text


def test_an_assigned_or_address_taken_local_is_left_alone():
    assigned = SOURCE.replace('    half = cx * 0.5f;', '    cx = 80.0f;\n    half = cx * 0.5f;')
    assert not any('cx_r' in text for text in children(assigned))
    taken = SOURCE.replace('    half = cx * 0.5f;', '    keep(&cx);\n    half = cx * 0.5f;')
    assert not any('cx_r' in text for text in children(taken))


def test_a_read_of_one_twin_is_renamed_to_a_sibling_one_at_a_time():
    from decomprepair.float_role_twins import TOGGLE
    source = SOURCE.replace('f32 cx = 160.0f;\n', 'f32 cx = 160.0f;\n    f32 cz = 160.0f;\n')
    toggles = [text for family, text in variants(source, 'setup') if family == TOGGLE]
    assert toggles
    assert any('place(obj, cz, cy, 320.0f' in text for text in toggles)
    assert any('half = cz * 0.5f;' in text for text in toggles)
    assert all(text != source for text in toggles)


def test_the_twins_this_family_writes_are_toggled_by_the_next_step():
    from decomprepair.float_role_twins import TOGGLE
    twin = children(SOURCE)[0]
    toggled = [text for family, text in variants(twin, 'setup') if family == TOGGLE]
    assert any('place(obj, cx_r3, cy_r2, 320.0f' in text for text in toggled)
