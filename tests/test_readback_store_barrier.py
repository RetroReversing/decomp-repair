"""A store moved between a member's store and the statement that reads it back (a player update, 1225 -> 745)."""
from decomprepair.readback_store_barrier import FAMILY, REPAIR, variants

SOURCE = """void land(Actor *a, Rec *r)
{
    a->vel = 0.0f;
    a->pad = 0.0f;
    a->angle = turn;
    r->angle = a->angle;
    done(a);
}
"""


def children(source):
    return [text for family, text in variants(source, 'land') if family == FAMILY]


def test_the_store_before_the_read_member_moves_between_it_and_the_read():
    found = children(SOURCE)
    assert len(found) == 1
    moved = found
    assert moved[0].index('a->angle = turn;') < moved[0].index('a->pad = 0.0f;') < moved[0].index('r->angle = a->angle;')
    assert moved[0].index('a->vel = 0.0f;') < moved[0].index('a->angle = turn;')


def test_a_store_that_the_next_two_statements_mention_stays_put():
    assert children(SOURCE.replace('a->pad = 0.0f;', 'a->pad = a->angle;')) == []
    assert children(SOURCE.replace('r->angle = a->angle;', 'r->angle = a->pad;')) == []


def test_a_call_in_the_values_or_a_compound_assignment_is_left_alone():
    assert children(SOURCE.replace('a->angle = turn;', 'a->angle = spin();')) == []
    assert children(SOURCE.replace('a->pad = 0.0f;', 'a->pad += 1;')) == []


def test_it_declares_itself():
    assert REPAIR['variants'] is variants and FAMILY in REPAIR['families']
