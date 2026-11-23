from decomprepair import registry
from decomprepair.loop_literal_local import FAMILY, REPAIR, variants

SOURCE = """void clear_voices(Entity *e) {
    s32 n;
    s32 var_s1;
    void *cursor;
    cursor = (void *) (0x3C + ((s32) e));
    var_s1 = 0xF;
    do {
        *((s32 *) (((char *) cursor) + 0xF80)) = -1;
        var_s1 -= 1;
        cursor -= 4;
    } while (var_s1 >= 0);
}
"""


def children(source=SOURCE):
    return [c for f, c in variants(source, 'clear_voices') if f == FAMILY]


def test_the_literal_is_set_above_the_initialisations_and_stored_from_the_local():
    first = children()[0]
    assert first.index('neg_1 = -1;') < first.index('cursor = ')
    assert '= neg_1;' in first and '= -1;' not in first.replace('neg_1 = -1;', '')
    assert 's32 neg_1;' in first


def test_a_second_child_swaps_the_last_two_initialisations_as_well():
    swapped = children()[1]
    assert swapped.index('neg_1 = -1;') < swapped.index('var_s1 = 0xF;') < swapped.index('cursor = ')


def test_a_loop_with_a_call_is_left_alone():
    assert children(SOURCE.replace('var_s1 -= 1;', 'var_s1 -= probe(1);')) == []


def test_a_zero_store_is_left_alone():
    assert children(SOURCE.replace('= -1;', '= 0;')) == []


def test_it_declares_itself():
    assert REPAIR['variants'] is variants
    assert FAMILY in {family for entry in registry.declared() for family in entry.families}
