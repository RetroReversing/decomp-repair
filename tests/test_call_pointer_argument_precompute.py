"""A call's base + offset argument computed before the if that sets another argument (a player update, 1940 -> 1420)."""
from decomprepair.call_pointer_argument_precompute import FAMILY, REPAIR, variants

SOURCE = """void tick(void *obj)
{
    s32 var_a2;
    var_a2 = 1;
    if (gFlags & 0x40)
    {
        if (!(speed > 0.0f))
        {
            var_a2 = 0;
        }
        play_marker(obj + 0x24, 1, var_a2);
    }
    else if (gFlags & 2)
    {
        if (!(speed > 0.0f))
        {
            var_a2 = 0;
        }
        play_track(obj + 0x24, 1, var_a2);
    }
}
"""


def children(source):
    return [text for family, text in variants(source, 'tick') if family == FAMILY]


def test_each_call_and_both_together_are_offered():
    found = children(SOURCE)
    assert len(found) == 3
    both = [t for t in found if t.count('obj_plus_24 = obj + 0x24;') == 2]
    assert len(both) == 1
    child = both[0]
    assert '    void *obj_plus_24;\n' in child
    assert child.index('obj_plus_24 = obj + 0x24;') < child.index('if (!(speed > 0.0f))')
    assert 'play_marker(obj_plus_24, 1, var_a2);' in child and 'play_track(obj_plus_24, 1, var_a2);' in child


def test_an_if_that_mentions_the_base_or_a_call_in_the_argument_is_left_alone():
    assert children(SOURCE.replace('var_a2 = 0;', 'var_a2 = use(obj);')) == []
    assert children(SOURCE.replace('play_marker(obj + 0x24, 1, var_a2);', 'play_marker(obj + 0x24, probe(), var_a2);').replace('play_track(obj + 0x24', 'play_track(obj')) == []


def test_a_base_that_is_not_a_void_pointer_is_left_alone():
    assert children(SOURCE.replace('void *obj', 's32 obj')) == []


def test_it_declares_itself():
    assert REPAIR['variants'] is variants and FAMILY in REPAIR['families']
