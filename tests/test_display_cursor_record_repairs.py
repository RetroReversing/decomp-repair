from decomprepair import display_cursor_record_repairs as r

DRAFT = '''extern void * volatile sCursor;
void f(void *arg0)
{
    void *a;
    void *b;
    void *c;
    a = sCursor;
    *((s32 *) (((char *) a) + 0)) = 0xE7000000;
    *((s32 *) (((char *) a) + 0xC)) = 0x300000;
    *((s32 *) (((char *) a) + 4)) = 0;
    *((s32 *) (((char *) a) + 8)) = 0xE3000A01;
    sCursor = a + 8;
    sCursor = a + 0x10;
    b = a + 0x10;
    c = sCursor;
    *((s32 *) (((char *) b) + 0)) = arg0;
    sCursor = c + 8;
}
'''


def _by_family(source=DRAFT):
    return {family: text for family, text in r.variants(source, 'f')}


def test_the_cursor_becomes_a_record_pointer_without_volatile():
    out = _by_family()['display_cursor_record']
    assert 'typedef struct { s32 w0; s32 w1; } CursorRecord;\nextern CursorRecord *sCursor;' in out
    assert 'volatile' not in out


def test_each_word_is_a_member_of_its_command_record():
    out = _by_family()['display_cursor_record']
    assert '((CursorRecord *) a)[0].w0 = 0xE7000000;' in out
    assert '((CursorRecord *) a)[1].w1 = 0x300000;' in out
    assert '((CursorRecord *) b)[0].w0 = arg0;' in out


def test_each_advance_moves_before_the_first_word_of_its_command():
    out = _by_family()['display_cursor_record']
    lines = [line.strip() for line in out.split('\n')]
    assert lines.index('sCursor = a + 0x8;') < lines.index('((CursorRecord *) a)[0].w0 = 0xE7000000;')
    # command 1's advance sits before its first word (the `+ 0xC` store comes before `+ 8` in this draft)
    assert lines.index('sCursor = a + 0x10;') < lines.index('((CursorRecord *) a)[1].w1 = 0x300000;')
    assert lines.index('((CursorRecord *) a)[0].w0 = 0xE7000000;') < lines.index('sCursor = a + 0x10;')


def test_the_after_form_puts_each_advance_behind_its_last_word():
    out = _by_family()['display_cursor_record_after']
    lines = [line.strip() for line in out.split('\n') if line.strip()]
    assert lines.index('((CursorRecord *) a)[0].w1 = 0;') + 1 == lines.index('sCursor = a + 0x8;')


def test_a_moved_advance_never_names_a_pointer_defined_later():
    # `b` is defined after command 1's first word: the advance is written from `a`
    out = _by_family()['display_cursor_record']
    assert 'sCursor = b' not in out


def test_one_advance_is_left_alone():
    src = DRAFT.replace('    sCursor = a + 0x10;\n', '')
    assert r.variants(src, 'f') == []


def test_a_global_that_is_not_a_plain_pointer_is_left_alone():
    assert r.variants(DRAFT.replace('extern void * volatile sCursor;', 'extern s32 sCursor;'), 'f') == []


def test_an_existing_record_type_is_left_alone():
    assert r.variants('typedef int CursorRecord;\n' + DRAFT, 'f') == []


WORDS = '''typedef struct { int value; } Field_0;
extern int * volatile sCursor;
extern unsigned char gR, gG, gB, gA;
void g(unsigned char *arg0)
{
    int *t;
    t = sCursor;
    sCursor = t + 2;
    ((Field_0 *) t)->value = 0xFA000000;
    sCursor = t + 4;
    *((s32 *) (((char *) t) + 0xC)) = (gR << 24) | gG;
    *((s32 *) (((char *) t) + 4)) = (gB << 8) | arg0[0x82];
    *((s32 *) (((char *) t) + 8)) = 0xFB000000;
}
'''


def test_a_word_typed_cursor_counts_its_advances_in_words_and_a_one_member_record_is_a_word_store():
    out = _by_family(WORDS.replace('void g', 'void f'))['display_cursor_record_ordered']
    assert 'extern CursorRecord *sCursor;' in out and 'volatile' not in out
    # `t + 2` is eight bytes for an int cursor: command 1 starts at `t + 4` words
    assert 'sCursor = t + 0x2;' in out and 'sCursor = t + 0x4;' in out
    assert '((CursorRecord *) t)[0].w0 = 0xFA000000;' in out
    assert '((CursorRecord *) t)[1].w1 = (gR << 24) | gG;' in out


def test_the_ordered_form_writes_each_command_whole_in_the_slots_the_stores_held():
    out = _by_family(WORDS.replace('void g', 'void f'))['display_cursor_record_ordered']
    lines = [line.strip() for line in out.split('\n') if line.strip()]
    order = [line for line in lines if line.startswith('((CursorRecord *)')]
    assert [line.split(' = ')[0] for line in order] == ['((CursorRecord *) t)[0].w0', '((CursorRecord *) t)[0].w1',
                                                         '((CursorRecord *) t)[1].w0', '((CursorRecord *) t)[1].w1']
    assert lines.index('sCursor = t + 0x2;') < lines.index(order[0])
    assert lines.index('sCursor = t + 0x4;') < lines.index(order[2])


def test_stores_in_different_branches_are_never_reordered_or_moved_across():
    branched = WORDS.replace('void g', 'void f').replace('    *((s32 *) (((char *) t) + 4))', '    if (arg0)\n    {\n    *((s32 *) (((char *) t) + 4))').replace(
        '(gB << 8) | arg0[0x82];', '(gB << 8) | arg0[0x82];\n    }')
    assert 'display_cursor_record_ordered' not in _by_family(branched)
