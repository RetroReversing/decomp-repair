"""A float local's quotient taken in place before the call that converts it."""
from decomprepair import registry
from decomprepair.float_quotient_argument_stage import FAMILIES, FAMILY, REPAIR, variants

SOURCE = """void slew(s16 arg0, s32 target) {
    s32 step;
    f32 temp;

    step = table[arg0];
    temp = (f32) step;
    set_speed(D_TABLE[arg0], (s32) (temp / D_SCALE));
    D_VALUE[arg0] = (s16) step;
}
"""


def kids(source=SOURCE):
    return [c for f, c in variants(source, 'slew') if f == FAMILY]


def test_the_quotient_is_stored_back_and_the_argument_reads_the_local():
    child = kids()[0]
    assert 'temp = temp / D_SCALE;\n    set_speed(D_TABLE[arg0], (s32) temp);' in child


def test_a_local_read_later_is_left_alone():
    assert not kids(SOURCE.replace('D_VALUE[arg0] = (s16) step;', 'D_VALUE[arg0] = (s16) temp;'))


def test_only_declared_float_locals_are_staged():
    assert not kids(SOURCE.replace('f32 temp;', 's32 temp;'))
    assert not kids(SOURCE.replace('(s32) (temp / D_SCALE)', '(s32) (step / D_SCALE)'))


def test_the_module_declares_itself():
    assert FAMILIES == (FAMILY,)
    assert REPAIR['families'] == FAMILIES
    assert registry.problems(registry.get('float_quotient_argument_stage')) == []
