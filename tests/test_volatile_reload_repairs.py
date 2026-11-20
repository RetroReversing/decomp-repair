from decomprepair import volatile_reload_repairs as r

DRAFT = '''extern void *D_800B5B14;
extern s32 D_800B0000;
void f(void) {
    void **__base_D_800B5B14;
    __base_D_800B5B14 = &D_800B5B14;
    g(*__base_D_800B5B14);
    (*(f32 *)((char *)(D_800B5B14) + 0x24)) = 0.85f;
    (*(f32 *)((char *)(D_800B5B14) + 0x28)) = 0.25f;
    D_800B0000 = 1;
}
'''


def test_a_pointer_stored_through_twice_becomes_volatile():
    out = [t for _, t in r.variants(DRAFT, 'f')]
    assert len(out) == 1
    assert 'extern void *volatile D_800B5B14;' in out[0]
    assert 'void *volatile *__base_D_800B5B14;' in out[0]
    assert 'extern s32 D_800B0000;' in out[0]


def test_a_single_store_is_left_alone():
    src = DRAFT.replace('    (*(f32 *)((char *)(D_800B5B14) + 0x28)) = 0.25f;\n', '')
    assert r.variants(src, 'f') == []


def test_reads_and_comparisons_are_not_stores():
    src = DRAFT.replace(') = 0.85f;', ') == 0.85f;').replace(') = 0.25f;', ') == 0.25f;')
    assert r.variants(src, 'f') == []


def test_an_already_volatile_global_is_left_alone():
    assert r.variants(DRAFT.replace('extern void *D_', 'extern void *volatile D_'), 'f') == []
