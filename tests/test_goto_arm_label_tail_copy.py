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
    assert len(found) == 2
    after = [t for t in found if t.index('w = 0xA0;') < t.index('h = 0x78;', t.index('w = 0xA0;'))][0]
    assert 'w = 0xA0;\n            h = 0x78;\n            goto join;' in after
    before = [t for t in found if t is not after][0]
    assert 'h = 0x78;\n            w = 0xA0;\n            goto join;' in before
    assert 'goto shared;' not in after and 'goto shared;' not in before


def test_an_arm_that_ends_in_a_jump_or_is_not_followed_by_a_goto_is_left_alone():
    assert children(SOURCE.replace('h = 0x78;\n', 'h = 0x78;\n            return;\n')) == []
    assert children(SOURCE.replace('        goto join;\n', '')) == []


def test_it_declares_itself():
    assert REPAIR['variants'] is variants and FAMILY in REPAIR['families']
