"""A copy statement's load read early into a local, the statement storing the local where it stood.

Synthetic shapes of two 60 -> 0 matches (N64, sn-n64-281): an object initialiser whose last statement copies a float
member after five stores, and an update `x = x + K` of a member whose read the target does before a neighbour's update."""
from decomprepair import copy_load_hoist as c

COPY = '''void init(void *a, void *b) {
    s16 *p;

    p = look(b);
    M2C_FIELD(a, f32 *, 4) = (f32) M2C_FIELD(b, f32 *, 4);
    do { M2C_FIELD(a, f32 *, 8) = (f32) (M2C_FIELD(b, f32 *, 8) + (f32) *p); } while (0);
    M2C_FIELD(a, s32 *, 0x64) = 0x19;
    M2C_FIELD(a, s32 *, 0x80) = 0x14;
    M2C_FIELD(a, void **, 0xA4) = b;
    M2C_FIELD(a, f32 *, 0xC) = (f32) M2C_FIELD(b, f32 *, 0xC);
}
'''

UPDATE = '''void tick(void *a) {
    s32 t;

    reset(a);
    M2C_FIELD(a, s32 *, 0x18) = (s32) (M2C_FIELD(a, s32 *, 0x18) + 0x4B4);
    M2C_FIELD(a, s32 *, 0x10) = (s32) (M2C_FIELD(a, s32 *, 0x10) + 0x1000);
    do { M2C_FIELD(a, s32 *, 0x80) = (s32) (M2C_FIELD(a, s32 *, 0x80) + 0xA); } while (0);
}
'''


def _texts(source, name):
    found = c.variants(source, name)
    assert all(family == c.FAMILY for family, _ in found)
    return [text for _, text in found]


def test_the_copys_load_is_read_after_each_earlier_store():
    texts = _texts(COPY, 'init')
    assert len(texts) == 4  # after the stores of 0x80, 0x64, 8 and 4; not beside the copy, not above the call
    wanted = ('    do { M2C_FIELD(a, f32 *, 8) = (f32) (M2C_FIELD(b, f32 *, 8) + (f32) *p); } while (0);\n'
              '    temp_copy = (f32) M2C_FIELD(b, f32 *, 0xC);\n    M2C_FIELD(a, s32 *, 0x64) = 0x19;')
    assert any(wanted in text for text in texts)
    for text in texts:
        assert '    f32 temp_copy;\n' in text.split('p = look(b);')[0]
        assert text.rstrip().endswith('M2C_FIELD(a, f32 *, 0xC) = temp_copy;\n}')


def test_the_unfolded_spelling_is_read_too():
    text = COPY.replace('M2C_FIELD(a, f32 *, 0xC)', '*(f32 *)((s8 *)a + 0xC)').replace(
        'M2C_FIELD(b, f32 *, 0xC)', '*(f32 *)((s8 *)b + 0xC)')
    assert any('temp_copy = (f32) *(f32 *)((s8 *)b + 0xC);' in t for t in _texts(text, 'init'))


def test_a_store_over_the_loaded_bytes_stops_the_hoist():
    text = COPY.replace('M2C_FIELD(a, s32 *, 0x80) = 0x14;', 'M2C_FIELD(b, s32 *, 0xC) = 0x14;')
    [only] = _texts(text, 'init')  # the anchor after that store; the earlier ones would cross it
    assert '0x14;\n    temp_copy = (f32) M2C_FIELD(b, f32 *, 0xC);\n' in only


def test_a_call_or_a_rewritten_base_stops_the_hoist():
    assert _texts(COPY.replace('M2C_FIELD(a, s32 *, 0x80) = 0x14;', 'poke(a);'), 'init') == []
    [only] = _texts(COPY.replace('M2C_FIELD(a, s32 *, 0x80) = 0x14;', 'b = a;'), 'init')
    assert 'b = a;\n    temp_copy = ' in only


def test_a_function_with_a_volatile_or_an_untyped_cell_is_left_alone():
    assert _texts(COPY.replace('s16 *p;', 'volatile s16 *p;'), 'init') == []
    assert _texts(COPY.replace('f32 *, 0xC) = (f32)', 'M2C_UNK *, 0xC) = (f32)'), 'init') == []


def test_an_update_read_goes_to_a_local_with_the_write_kept_and_unfenced():
    texts = _texts(UPDATE, 'tick')
    held = '    temp_copy = M2C_FIELD(a, s32 *, 0x80);\n'
    assert any(held in t and 'do { M2C_FIELD(a, s32 *, 0x80) = (s32) (temp_copy + 0xA); } while (0);' in t for t in texts)
    assert any(held in t and '\n    M2C_FIELD(a, s32 *, 0x80) = (s32) (temp_copy + 0xA);' in t for t in texts)
    assert any(t.index(held) < t.index('0x10) = ') for t in texts)


def test_a_compound_update_and_an_unfenced_write_are_fenced_as_well():
    text = UPDATE.replace('do { M2C_FIELD(a, s32 *, 0x80) = (s32) (M2C_FIELD(a, s32 *, 0x80) + 0xA); } while (0);',
                          'M2C_FIELD(a, s32 *, 0x80) += 0xA;')
    texts = _texts(text, 'tick')
    assert any('M2C_FIELD(a, s32 *, 0x80) = temp_copy + 0xA;' in t and 'do {' not in t.split('0x10)')[1] for t in texts)
    assert any('do { M2C_FIELD(a, s32 *, 0x80) = temp_copy + 0xA; } while (0);' in t for t in texts)


def test_a_name_in_use_is_not_reused():
    assert all('temp_copy1' in t for t in _texts(COPY.replace('s16 *p;', 's16 *p;\n    s32 temp_copy;'), 'init'))
