"""endian_word_load where the swapped offset is added inside a call's argument and kept in a second local (made-up code)."""
from decomprepair.endian_word_load import BASE, WHOLE, variants

SWAP = '((((at & 0xFF) << 8) + ((u32) (at & 0xFF00) >> 8)) << 0x10) + (((top & 0xFF) << 8) + (top >> 8))'

DRAFT = f'''extern M2C_UNK D_B0001000;

void load(u8 *arg0, s32 buffer) {{
    s32 offset;
    u32 at;
    u32 top;
    void *entry;

    read(0, (s32) &D_B0001000, buffer);
    read(1, (s32) &D_B0001000, buffer);
    entry = find(buffer, arg0);
    if (entry != NULL) {{
        at = M2C_FIELD(entry, u32 *, 0x20);
        top = at >> 0x10;
        offset = {SWAP};
        flush(buffer);
        read(2, (s32) (&D_B0001000 + offset), buffer, offset);
    }}
}}
'''


def test_the_sum_in_an_argument_is_a_cursor_stepped_before_the_call():
    child = dict(variants(DRAFT, 'load'))[BASE]
    assert 'repair_base = (s32) &D_B0001000;' in child
    assert 'read(0, repair_base, buffer);' in child and 'read(2, repair_base, buffer, offset);' in child
    assert child.index('repair_base += offset;') < child.index('flush(buffer);')


def test_the_swapped_word_goes_back_into_its_own_local():
    child = dict(variants(DRAFT, 'load'))[WHOLE]
    assert 's32 offset;' not in child
    assert 'at = ((((at & 0xFF) << 8)' in child
    assert 'repair_base += at;' in child and 'read(2, repair_base, buffer, at);' in child


def test_a_copy_read_before_is_left_alone():
    before = DRAFT.replace('    read(0,', '    use(offset);\n    read(0,')
    assert all('s32 offset;' in text for _, text in variants(before, 'load'))
