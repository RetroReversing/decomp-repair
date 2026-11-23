"""A result local for the arms of an in-place update (a scroll-window offset, 2155 -> 1380)."""
from decomprepair.arm_result_local import FAMILY, variants

SOURCE = """void settle(Window *w)
{
    if (check(w) > 2.0f) {
        s32 quarter = w->offset >> 2;
        s32 change = -quarter;
        s32 offset = w->offset;
        if (change < -8)
            offset -= 8;
        else if (change <= 8)
            offset -= quarter;
        else
            offset += 8;
        w->offset = offset;
    } else {
        w->offset = 0;
    }
}
"""


def test_each_arm_writes_a_result_local_that_is_stored_once():
    [(family, text)] = variants(SOURCE, 'settle')
    assert family == FAMILY
    assert 's32 result;' in text
    assert 'if (change < -8)\n            result = offset - 8;' in text
    assert 'else if (change <= 8)\n            result = offset - quarter;' in text
    assert 'else\n            result = offset + 8;' in text
    assert 'w->offset = result;' in text
    assert 'w->offset = offset;' not in text


def test_braced_arms_keep_their_braces():
    braced = SOURCE.replace('offset -= 8;', '{ offset -= 8; }').replace('offset += 8;', '{ offset += 8; }')
    [(_, text)] = variants(braced, 'settle')
    assert '{ result = offset - 8; }' in text and '{ result = offset + 8; }' in text


def test_a_chain_without_a_final_else_leaves_the_result_unset_on_one_path():
    open_chain = SOURCE.replace('        else\n            offset += 8;\n', '')
    assert variants(open_chain, 'settle') == []


def test_an_arm_that_is_not_a_compound_assignment_is_left_alone():
    other = SOURCE.replace('offset += 8;', 'offset = 8;')
    assert variants(other, 'settle') == []


def test_the_local_read_after_the_store_is_not_replaced():
    later = SOURCE.replace('        w->offset = offset;\n', '        w->offset = offset;\n        use(offset);\n')
    assert variants(later, 'settle') == []


def test_an_arm_that_reads_the_local_in_its_operand_is_left_alone():
    chained = SOURCE.replace('offset -= quarter;', 'offset -= offset >> 1;')
    assert variants(chained, 'settle') == []
