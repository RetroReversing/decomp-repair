from decomprepair import guard_load_split as split

SOURCE = '''extern u32 gTotal;
extern void *gList[];
extern void *gPick;

void *f(void *self, s32 flags) {
    void *other;
    void *best;
    u32 total = gTotal;
    s32 i;
    u16 kind;

    i = 0;
    best = NULL;
    if (best < total) {
        do {
            i += 1;
        } while (i < total);
    }
    for (i = 0; i < 4; i++) {
        void **slot = &gList[i];
        if ((((*slot) != NULL) && ((*slot) != self)) && (!((*((f32 *)(((char *)(*slot)) + 0x74))) <= 0.0f)))
        {
            other = FIELD(*slot, void *, 0x6C);
            kind = *((u16 *)(((char *)(*slot)) + 0x78));
            best = other;
        }
    }
    return best;
}
'''


def families(source):
    return {family: text for family, text in split.variants(source, 'f')}


def test_the_load_moves_ahead_of_the_last_test():
    text = families(SOURCE)['guard_load_first']
    assert 'if (((*slot) != NULL) && (((*slot) != self)))' in text
    assert 'other = FIELD(*slot, void *, 0x6C);\n      if ((!((*((f32 *)(((char *)(*slot)) + 0x74))) <= 0.0f)))' in text
    assert text.count('{') == text.count('}')
    assert 'u32 total = gTotal;' in text


def test_the_bound_is_assigned_after_a_guard_that_reads_the_global():
    text = families(SOURCE)['guard_bound_copy']
    assert '    u32 total;\n' in text
    assert 'if (best < gTotal)' in text
    assert '{\n      total = gTotal;' in text or 'total = gTotal;' in text.split('if (best < gTotal)')[1][:60]
    assert 'while (i < total)' in text


def test_both_edits_come_as_one_child_because_each_is_worse_alone():
    both = families(SOURCE)['guard_load_split']
    assert 'if (best < gTotal)' in both and 'if ((!((*((f32 *)' in both
    assert both.count('{') == both.count('}')


def test_a_chain_of_one_test_or_a_guard_that_does_not_read_the_bound_is_left_alone():
    assert 'guard_load_first' not in families(SOURCE.replace('(((*slot) != NULL) && ((*slot) != self)) && ', ''))
    assert 'guard_bound_copy' not in families(SOURCE.replace('if (best < total)', 'if (best < 3)'))
    assert 'guard_load_first' not in families(SOURCE.replace('other = FIELD(*slot, void *, 0x6C);', 'other = pick(*slot);'))
    assert 'guard_load_first' not in families(SOURCE.replace('other = FIELD(*slot, void *, 0x6C);', 'other = 0;'))


def test_the_module_declares_itself_to_the_registry():
    from decomprepair import registry
    declared = {r.module: r for r in registry.declared()}
    assert 'guard_load_split' in declared and not registry.problems(declared['guard_load_split'])
