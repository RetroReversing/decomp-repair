from decomprepair.display_value_stage import FAMILY, variants

DRAFT = '''typedef struct { s32 value; } Field_0;
extern s32 * volatile sCursor;
extern unsigned char sTint;
void f(u8 *arg0, u8 *table)
{
    s32 *t;
    t = sCursor;
    sCursor = t + 2;
    ((Field_0 *) t)->value = 0xFA000000;
    *((s32 *) (((char *) t) + 4)) = (((arg0[0x7F] * table[0x64]) >> 8) << 24) | arg0[0x82];
    use(arg0);
}
'''


def _found(source=DRAFT):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_a_heavy_value_is_computed_in_a_block_scoped_local_before_the_cursor_is_read():
    found = _found()
    assert len(found) == 2  # the staged function, then the same with the command's words as members
    out = found[0]
    assert out.index('u32 stage =') < out.index('t = sCursor;') < out.index('= stage;')
    assert '(((arg0[0x7F] * table[0x64]) >> 8) << 24) | arg0[0x82];\n    t = sCursor;' in out.replace('\n    \n', '\n')
    assert out.count('{ u32 stage') == 1 and out.rstrip().endswith('}')


def test_a_constant_value_a_value_after_a_call_or_a_different_pointer_is_left_alone():
    assert not _found(DRAFT.replace('(((arg0[0x7F] * table[0x64]) >> 8) << 24) | arg0[0x82]', '0x100'))
    assert not _found(DRAFT.replace('    sCursor = t + 2;', '    sCursor = t + 2;\n    prepare();'))
    assert not _found(DRAFT.replace('((s32 *) (((char *) t) + 4))', '((s32 *) (((char *) u) + 4))'))


def test_a_cursor_record_member_store_counts_too():
    record = DRAFT.replace('*((s32 *) (((char *) t) + 4)) =', '((CursorRecord *) t)[0].w1 =')
    assert len(_found(record)) == 1


def test_a_second_staged_value_gets_its_own_local():
    first = _found()[0]
    again = first.replace('    use(arg0);', '    t = sCursor;\n    sCursor = t + 2;\n    *((s32 *) (((char *) t) + 4)) = (arg0[0x7F] * table[0x64]) << 8;\n    use(arg0);')
    assert any('stage_2' in text for text in _found(again))


def test_the_combined_child_writes_the_words_as_members_of_one_record():
    combined = _found()[1]
    assert 'typedef struct { s32 w0; s32 w1; } CursorRecord;' in combined and 'volatile' not in combined
    assert '((CursorRecord *) t)[0].w0 = 0xFA000000;' in combined and '((CursorRecord *) t)[0].w1 = stage;' in combined
