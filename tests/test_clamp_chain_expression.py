"""A three-way clamp written into a local in every arm, stored once: the expression it came from (3265 -> 2415)."""
from decomprepair.clamp_chain_expression import FAMILY, variants

SOURCE = """void step(Window *w)
{
    s32 proposed;
    u8 selected;

    if (w->limit < sum) {
        proposed = w->selected + 1;
        if (proposed < 0)
            selected = 0;
        else if (proposed > w->count - 1)
            selected = w->count - 1;
        else
            selected = proposed;
        w->selected = selected;
    }
    selected = w->selected;
}
"""


def test_the_clamp_becomes_one_conditional_expression_stored_directly():
    [(family, text)] = variants(SOURCE, 'step')
    assert family == FAMILY
    assert ('        w->selected = w->selected + 1 < 0 ? 0 : '
            'w->selected + 1 > w->count - 1 ? w->count - 1 : w->selected + 1;\n') in text
    assert 'proposed =' not in text and 'selected = 0;' not in text


def test_a_value_read_afterwards_keeps_the_local():
    assert variants(SOURCE.replace('    selected = w->selected;\n', '    use(selected);\n'), 'step') == []
    assert variants(SOURCE.replace('    selected = w->selected;\n', '    use(proposed);\n'), 'step') == []


def test_a_call_in_the_clamped_expression_is_not_repeated():
    assert variants(SOURCE.replace('proposed = w->selected + 1;', 'proposed = next(w) + 1;'), 'step') == []


def test_the_last_arm_must_take_the_clamped_value_itself():
    assert variants(SOURCE.replace('selected = proposed;', 'selected = proposed + 1;'), 'step') == []


def test_braced_arms_are_read_too():
    braced = SOURCE.replace('selected = 0;', '{ selected = 0; }').replace('selected = proposed;', '{ selected = proposed; }')
    [(_, text)] = variants(braced, 'step')
    assert 'w->selected = w->selected + 1 < 0 ? 0 :' in text
