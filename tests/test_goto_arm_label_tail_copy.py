"""A labelled arm that falls out of its if onto the goto after it, copied where a goto jumps into it (a player update, 745 -> 570)."""
from decomprepair.goto_arm_label_tail_copy import FAMILY, REPAIR, variants

SOURCE = """void pick(s32 n)
{
    s32 w;
    s32 h;
    w = 320;
    h = 240;
    if (n != 2)
    {
        if (n < 5)
        {
            w = 0xA0;
            goto shared;
        }
    }
    else
    {
        if (!(gFlip == 1))
        {
            shared:
            h = 0x78;
        }
        else
        {
            w = 0xA0;
        }
        goto join;
    }
    join:
    use(w, h);
}
"""


def children(source):
    return [text for family, text in variants(source, 'pick') if family == FAMILY]


def test_the_arm_is_copied_after_and_before_the_assignment_with_the_join_goto():
    found = children(SOURCE)
    assert len(found) == 4
    plain = [t for t in found if 'if (!(gFlip == 1))' in t]
    assert len(plain) == 2
    after = [t for t in plain if 'w = 0xA0;\n            h = 0x78;\n            goto join;' in t]
    before = [t for t in plain if 'h = 0x78;\n            w = 0xA0;\n            goto join;' in t]
    assert len(after) == 1 and len(before) == 1
    assert all('goto shared;' not in t for t in found)


def test_each_copy_is_also_offered_with_the_polarity_of_the_if_that_held_the_arm_swapped():
    swapped = [t for t in children(SOURCE) if 'if (gFlip == 1)' in t]
    assert len(swapped) == 2
    child = [t for t in swapped if 'w = 0xA0;\n            h = 0x78;\n            goto join;' in t][0]
    # the arms trade places: the old else arm comes first, the labelled arm second
    assert child.index('w = 0xA0;', child.index('if (gFlip == 1)')) < child.index('shared:')
    assert 'else\n        {\n            shared:\n            h = 0x78;' in child


def test_an_arm_that_ends_in_a_jump_or_is_not_followed_by_a_goto_is_left_alone():
    assert children(SOURCE.replace('h = 0x78;\n', 'h = 0x78;\n            return;\n')) == []
    assert children(SOURCE.replace('        goto join;\n', '')) == []


def test_it_declares_itself():
    assert REPAIR['variants'] is variants and FAMILY in REPAIR['families']
