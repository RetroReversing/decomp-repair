from decomprepair import registry
from decomprepair.loop_argument_inline import FAMILY, REPAIR, variants

SOURCE = """void reset_all(Slot *s, s32 slot) {
    s32 i;
    s32 arg;
    i = 0;
    s->a = 0;
    do { arg = 0 & 0xFF; } while (0);
    do {
        reset(arg, slot & 0xFF);
        i += 1;
        arg = ((s32) i) & 0xFF;
    } while (i < 0x10);
}
"""


def children(source=SOURCE):
    return [c for f, c in variants(source, 'reset_all') if f == FAMILY]


def test_the_argument_is_the_counter_expression_at_the_call():
    got = children()
    assert len(got) == 1
    child = got[0]
    assert 'reset((((s32) i) & 0xFF), slot & 0xFF);' in child
    assert 'arg =' not in child and 'while (0)' not in child
    assert 'i += 1;' in child and 'while (i < 0x10);' in child


def test_a_plain_assignment_before_the_loop_is_dropped_too():
    got = children(SOURCE.replace('do { arg = 0 & 0xFF; } while (0);', 'arg = 0;'))
    assert got and 'arg = 0;' not in got[0]


def test_an_entry_value_that_is_not_the_expression_of_the_first_counter_value_is_left_alone():
    assert children(SOURCE.replace('arg = 0 & 0xFF;', 'arg = 5;')) == []


def test_an_argument_read_elsewhere_is_left_alone():
    assert children(SOURCE.replace('    s->a = 0;', '    s->a = arg;')) == []


def test_it_declares_itself():
    assert REPAIR['variants'] is variants
    assert FAMILY in {family for entry in registry.declared() for family in entry.families}
