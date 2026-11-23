"""A byte local lowered by one `if` and stored, through a second byte local (a scroll window, 905 -> 465)."""
from decomprepair.byte_update_copy import FAMILY, variants

SOURCE = """void settle(Window *w)
{
    s16 i;
    u8 selected;

    selected = w->selected;
    i = 0;
    while (i <= selected) {
        if (limit < sum) {
            if (i < 0)
                w->selected = 0;
            else {
                if (i <= selected)
                    selected = i;
                w->selected = selected;
            }
            break;
        }
        ++i;
        selected = w->selected;
    }
}
"""


def test_the_update_goes_through_a_second_byte_local_with_the_condition_on_either():
    found = [text for family, text in variants(SOURCE, 'settle') if family == FAMILY]
    assert len(found) == 2
    moved, kept = found
    assert 'u8 selected_copy;' in moved
    assert ('                selected_copy = selected;\n'
            '                if (i <= selected_copy) selected_copy = i;\n'
            '                w->selected = selected_copy;') in moved or 'if (i <= selected_copy)' in moved
    assert 'if (i <= selected)' in kept and 'selected_copy = i;' in kept and 'w->selected = selected_copy;' in kept
    assert 'while (i <= selected)' in moved and 'selected = w->selected;\n    }' in moved


def test_a_wide_local_is_left_alone():
    assert variants(SOURCE.replace('u8 selected;', 's32 selected;'), 'settle') == []


def test_an_update_that_reads_the_local_is_left_alone():
    assert variants(SOURCE.replace('selected = i;', 'selected = selected - 1;'), 'settle') == []


def test_an_if_with_an_else_is_left_alone():
    assert variants(SOURCE.replace('selected = i;\n', 'selected = i;\n                else\n                    selected = 0;\n'),
                    'settle') == []


def test_the_store_must_follow_the_update_at_once():
    assert variants(SOURCE.replace('                w->selected = selected;', '                use(selected);\n                w->selected = selected;'),
                    'settle') == []
