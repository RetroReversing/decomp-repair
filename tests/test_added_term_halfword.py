from decomprepair import added_term_halfword

SOURCE = '''
void func_80000000(void *arg0, u16 arg1) {
    u8 i;
    u8 j;
    for (i = 0; i < 7; i++) {
        for (j = 0; j < 6; j++) {
            draw(arg0, (s32) rec[arg1].x + ((i << 6) - 0x40), (s32) rec[arg1].y + ((j << 6) - 0x40), 11, 0);
        }
    }
}
'''


def children(source):
    return [child for _, child in added_term_halfword.variants(source, 'func_80000000')]


def test_both_terms_at_once_then_each():
    out = children(SOURCE)
    assert len(out) == 3
    assert 'x + (s16) ((i << 6) - 0x40)' in out[0] and 'y + (s16) ((j << 6) - 0x40)' in out[0]
    assert '(s16) ((i << 6) - 0x40)' in out[1] and '((j << 6) - 0x40)' in out[1]


def test_flat_and_left_grouped_sums():
    flat = SOURCE.replace('((i << 6) - 0x40), (s32)', '(i << 6) - 0x40, (s32)')
    assert 'x + (s16) ((i << 6) - 0x40), (s32)' in children(flat)[0]
    grouped = '''void func_80000000(s32 a, s32 i) { f(((s32) q + ((u8) i << 6)) - 0x40); }'''
    assert children(grouped) == ['''void func_80000000(s32 a, s32 i) { f(((s32) q + (s16) (((u8) i << 6) - 0x40))); }''']


def test_multiplication_and_mask():
    source = '''void func_80000000(s32 i) { f(base + ((i & 0xFF) * 64 - 64)); }'''
    assert children(source) == ['''void func_80000000(s32 i) { f(base + (s16) ((i & 0xFF) * 64 - 64)); }''']


def test_values_that_could_not_fit_stay():
    wide = '''void func_80000000(s32 i) { f(base + ((i << 6) - 0x40)); }'''
    large = '''void func_80000000(void) { u8 i; f(base + ((i << 8) - 0x40)); }'''
    not_added = '''void func_80000000(void) { u8 i; f(base - ((i << 6) - 0x40)); }'''
    assert children(wide) == [] and children(large) == [] and children(not_added) == []


def test_unparenthesised_shift_takes_the_constant_into_the_count():
    source = '''void func_80000000(void) { u8 i; f(base + i << 6 - 1); }'''
    assert children(source) == []


def test_added_constant():
    source = '''void func_80000000(void) { u8 i; f(base + ((i << 3) + 8)); }'''
    assert children(source) == ['''void func_80000000(void) { u8 i; f(base + (s16) ((i << 3) + 8)); }''']
