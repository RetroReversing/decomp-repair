"""m2c's float compare flags written back as the combined compares (a 1300-instruction routine, 2245 -> 1245)."""
from decomprepair.store_flag_compare_inline import FAMILY, REPAIR, variants

SOURCE = """void steer(Obj *o, f32 x)
{
    s32 var_v1_7;
    s32 var_v0_6;
    s32 var_v0_2;
    s32 var_v1_3;
    f32 t;
    var_v1_7 = 1;
    if (!(x <= 0.0002f))
    {
        var_v1_7 = 0;
    }
    var_v0_6 = 1;
    if (!(x >= (-0.0002f)))
    {
        var_v0_6 = 0;
    }
    t = 0.4f;
    if (((var_v1_7 ^ 1) | (var_v0_6 ^ 1)) != 0)
    {
        t = 0.1f;
    }
    o->t = t;
    var_v0_2 = 1;
    t = t * 2.0f;
    if (!(o->x <= 0.0002f))
    {
        var_v0_2 = 0;
    }
    var_v1_3 = 1;
    if (!(o->x >= (-0.0002f)))
    {
        var_v1_3 = 0;
    }
    if (var_v0_2 & var_v1_3)
    {
        o->x = 0.0f;
    }
}
"""


def children(source):
    return [text for family, text in variants(source, 'steer') if family == FAMILY]


def squash(text):
    return ' '.join(text.split())


def test_every_flag_goes_into_its_test_first():
    found = children(SOURCE)
    assert len(found) == 3
    first = squash(found[0])
    assert 'var_v' not in first
    assert 't = 0.4f; if (!(x <= 0.0002f) | !(x >= (-0.0002f))) { t = 0.1f; }' in first
    assert 't = t * 2.0f; if ((o->x <= 0.0002f) & (o->x >= (-0.0002f))) {' in first


def test_each_test_is_offered_alone():
    alone = [squash(text) for text in children(SOURCE)[1:]]
    assert any('if (!(x <= 0.0002f) | !(x >= (-0.0002f)))' in text and 'var_v0_2 = 1;' in text for text in alone)
    assert any('var_v1_7 = 1;' in text and 'if ((o->x <= 0.0002f) & (o->x >= (-0.0002f)))' in text for text in alone)


def test_a_compare_operand_written_between_keeps_the_flag():
    source = SOURCE.replace('    t = 0.4f;\n', '    t = 0.4f;\n    x = t;\n')
    assert all('if (!(x <= 0.0002f) |' not in text for text in children(source))


def test_a_memory_compare_does_not_move_past_a_store():
    source = SOURCE.replace('    var_v1_3 = 1;\n', '    var_v1_3 = 1;\n    o->y = 1.0f;\n')
    assert all('(o->x <= 0.0002f) &' not in text for text in children(source))


def test_a_flag_read_twice_is_left_alone():
    source = SOURCE.replace('    o->t = t;\n', '    o->t = var_v1_7;\n')
    found = children(source)
    assert found and all('var_v1_7 = 1;' in text and '(var_v1_7 ^ 1)' in text for text in found)


def test_it_declares_itself():
    assert REPAIR['variants'] is variants and REPAIR['families'] == (FAMILY,)
