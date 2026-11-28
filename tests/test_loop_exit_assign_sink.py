from decomprepair import loop_exit_assign_sink as family

SOURCE = """void f(s32 *cursor, u32 n)
{
    u8 *next;
    u32 k;

    k = 0;
    for (;;) {
        next = (u8 *) cursor;
        if (k >= n) goto done;
        cursor += 4;
        k++;
    }
done:
    use(next);
}
"""


def test_copy_moves_after_the_exit_label():
    [(name, child)] = family.variants(SOURCE, 'f')
    assert name == family.FAMILY
    assert 'for (;;) {\n        if (k >= n) goto done;' in child
    assert 'done:\n    next = (u8 *) cursor;\n    use(next);' in child


def test_break_form():
    source = SOURCE.replace('goto done;', 'break;').replace('done:\n', '')
    [(_, child)] = family.variants(source, 'f')
    assert '    }\n    next = (u8 *) cursor;\n    use(next);' in child


def test_a_loop_that_reads_the_copy_or_leaves_another_way_is_left_alone():
    assert family.variants(SOURCE.replace('cursor += 4;', 'cursor += *next;'), 'f') == []
    assert family.variants(SOURCE.replace('k++;', 'k++;\n        if (*cursor) return;'), 'f') == []
    assert family.variants(SOURCE.replace('k++;', 'k++;\n        if (*cursor) break;'), 'f') == []
    assert family.variants(SOURCE.replace('k >= n', 'k++ >= n'), 'f') == []
