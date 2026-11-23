"""The byte clamp as one conditional expression into a byte local (a scroll-window update, 3135 -> 2505)."""
from decomprepair.clamp_narrow_store import FAMILY, variants

SOURCE = """void update(Window *w)
{
    s16 total, sum;
    s32 proposed;
    u8 edge;

    edge = w->limit;
    if (total - w->scroll < edge) {
        proposed = total - edge;
        if (proposed < 0)
            proposed = 0;
        else if (proposed >= 256)
            proposed = 255;
        w->scroll = proposed;
        if (!w->fixed) {
            if ((u8)proposed < sum) {
                w->selected = 0;
            }
            proposed = w->selected + 1;
        }
    }
}
"""


def test_the_clamp_chain_becomes_a_conditional_expression_in_a_byte_local():
    [(family, text)] = variants(SOURCE, 'update')
    assert family == FAMILY
    assert 'u8 clamped;' in text
    assert 'clamped = total - edge < 0 ? 0 : total - edge >= 256 ? 255 : total - edge;' in text
    assert 'w->scroll = clamped;' in text
    assert 'if (clamped < sum)' in text
    assert 'if (proposed < 0)' not in text
    # the wide local stays for its other writes
    assert 'proposed = w->selected + 1;' in text


def test_a_wide_read_after_the_clamp_leaves_the_function_alone():
    assert variants(SOURCE.replace('if ((u8)proposed < sum)', 'if (proposed < sum)'), 'update') == []


def test_a_clamp_of_a_call_is_not_repeated():
    assert variants(SOURCE.replace('proposed = total - edge;', 'proposed = total - lookup(edge);'), 'update') == []


def test_a_wide_local_read_before_the_clamp_is_left_alone():
    source = SOURCE.replace('    edge = w->limit;\n', '    edge = w->limit;\n    use(proposed);\n')
    assert variants(source, 'update') == []


def test_the_other_arm_order_is_not_a_clamp_of_this_shape():
    swapped = SOURCE.replace('proposed >= 256', 'proposed >= 255')
    assert variants(swapped, 'update') == []


def test_a_member_with_the_locals_name_is_not_a_read_of_the_local():
    source = SOURCE.replace('s32 proposed;', 's32 proposed, selected;').replace(
        '            proposed = w->selected + 1;', '            proposed = w->proposed + 1;')
    [(_, text)] = variants(source.replace('(u8)proposed < sum', '(u8)proposed < w->proposed'), 'update')
    assert 'clamped < w->proposed' in text
