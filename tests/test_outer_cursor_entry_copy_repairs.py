from decomprepair import outer_cursor_entry_copy_repairs as repair

SOURCE = '''void f(void *list, s32 count, s32 inner)
{
    void *cursor;
    s32 i;
    cursor = list;
    if (count != 0)
    {
        do
        {
            g(*((u16 *) (((char *) cursor) + 6)));
            if (inner > 0)
            {
                i = 0;
                do
                {
                    h(*((s32 *) (((char *) cursor) + 0)), *((u16 *) (((char *) cursor) + 4)));
                    i += 1;
                }
                while (i < inner);
            }
            cursor += 8;
        }
        while (((u32) cursor) < ((u32) list + count * 8));
    }
}
'''


def test_inner_loop_reads_a_copy_taken_at_the_head_of_its_guard_or_before_it():
    found = [text for family, text in repair.variants(SOURCE, 'f')]
    assert len(found) == 2
    head, before = found
    for text in found:
        assert 'void *__repair_entry_cursor;' in text
        assert 'h(*((s32 *) (((char *) __repair_entry_cursor) + 0)), *((u16 *) (((char *) __repair_entry_cursor) + 4)));' in text
        # the outer loop keeps reading the cursor itself
        assert 'g(*((u16 *) (((char *) cursor) + 6)));' in text
    assert head.index('__repair_entry_cursor = cursor;') < head.index('i = 0;')
    assert before.index('i = 0;') < before.index('__repair_entry_cursor = cursor;') < before.index('do\n                {')


def test_a_cursor_the_inner_loop_steps_or_an_unrelated_name_is_left_alone():
    steps = SOURCE.replace('i += 1;', 'i += 1;\n                    cursor += 1;')
    no_outer_step = SOURCE.replace('            cursor += 8;\n', '')
    for source in (steps, no_outer_step):
        assert not repair.variants(source, 'f')
