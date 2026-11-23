"""A loop that tests the member itself, not a byte local reloaded at its bottom (a scroll window, 515 -> 230)."""
from decomprepair.member_test_loop import FAMILY, FAMILY_SWAP, variants

SOURCE = """void settle(Window *w)
{
    s16 i, sum;
    u8 selected, m;

    sum = 0;
    selected = w->selected;
    i = 0;
    while (i <= selected) {
        sum += w->rows[i].height;
        if (clamped < sum) {
            if (i < 0)
                w->selected = 0;
            else {
                m = selected;
                if (i <= m)
                    m = i;
                w->selected = m;
            }
            break;
        }
        ++i;
        selected = w->selected;
    }
    use(sum);
}
"""


def children(source=SOURCE):
    return dict((family, text) for family, text in variants(source, 'settle'))


def test_the_loop_tests_the_member_and_the_body_reads_it():
    plain = children()[FAMILY]
    assert 'selected = w->selected;' not in plain
    assert 'while (i <= w->selected) {' in plain
    assert 'm = w->selected;' in plain
    assert '++i;' in plain and plain.index('++i;') > plain.index('break;')
    assert 'if (i < 0)' in plain


def test_the_swap_child_also_writes_the_sign_test_the_other_way_round():
    swapped = children()[FAMILY_SWAP]
    assert 'while (i <= w->selected) {' in swapped
    assert 'if (i >= 0) {' in swapped and 'else w->selected = 0;' in swapped
    assert swapped.index('m = w->selected;') < swapped.index('w->selected = 0;')


def test_a_store_to_the_member_that_does_not_end_the_loop_keeps_the_local():
    source = SOURCE.replace('        ++i;\n', '        w->selected = 3;\n        ++i;\n')
    assert children(source) == {}


def test_a_read_of_the_local_after_the_loop_keeps_the_local():
    assert children(SOURCE.replace('    use(sum);', '    use(selected);')) == {}


def test_the_reload_must_be_the_last_statement():
    assert children(SOURCE.replace('        ++i;\n        selected = w->selected;\n', '        selected = w->selected;\n        ++i;\n')) == {}


def test_a_body_that_assigns_the_local_is_left_alone():
    assert children(SOURCE.replace('                m = selected;', '                selected = i;\n                m = selected;')) == {}
