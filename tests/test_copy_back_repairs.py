from decomprepair import copy_back_repairs as repair

SOURCE = '''
extern s32 D_800C469C;
void f(void *arg0, s32 k) {
    void *base;
    void *entry;
    void *other;
    void *cur;
    base = &D_800C469C;
    entry = (void *) (*((s8 *) arg0 + 0xE) * 0xE8);
    entry = (void *) (((char *) entry) + ((s32) base));
    other = (void *) (((char *) base) + *((s8 *) arg0 + 0x10) * 0xE8);
    switch (k) {
    default:
        cur = entry;
        use(cur);
        break;
    case 1:
        use(other);
    }
}
'''


def test_folds_two_sets_and_copies_back_after_the_first_copy():
    # A race function's table entry matched only with both edits: the fold alone scored 500, the copy-back alone 10.
    children = [text for family, text in repair.variants(SOURCE, 'f')]
    assert all(family == repair.FAMILY for family, _ in repair.variants(SOURCE, 'f'))
    fold = 'entry = (void *) (((char *) ((void *) (*((s8 *) arg0 + 0xE) * 0xE8))) + ((s32) base));'
    both = [text for text in children if fold in text and 'cur = entry;\n        entry = cur;' in text]
    assert len(both) == 1
    assert 'entry = (void *) (*((s8 *)' not in both[0]
    assert any(fold in text and 'entry = cur;' not in text for text in children)
    assert any(fold not in text and 'entry = cur;' in text for text in children)


def test_leaves_a_first_set_with_a_call_alone():
    source = SOURCE.replace('(*((s8 *) arg0 + 0xE) * 0xE8)', '(get(arg0) * 0xE8)')
    assert not any('(get(arg0) * 0xE8))) +' in text for _, text in repair.variants(source, 'f'))


def test_no_fold_when_the_second_set_reads_the_local_twice():
    source = SOURCE.replace('+ ((s32) base));', '+ ((s32) entry));')
    assert all('entry = (void *) (*((s8 *)' in text for _, text in repair.variants(source, 'f'))
