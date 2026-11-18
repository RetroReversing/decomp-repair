"""A call's `BASE + (INDEX * C)` argument staged as an element index, then the base, as the source had it."""
from decomprepair import call_index_staging_repairs as c

SOURCE = '''void f(void *arg0) {
    u8 i;

    for (i = 0; i < 4; i++) {
        M2C_FIELD(arg0, s32 (**)(s32, s32), 4)(M2C_FIELD(arg0, s32 *, 0) + (i * 0xC), M2C_FIELD(arg0, u8 *, 0x18) == i);
    }
}
'''


def test_integer_and_pointer_staging():
    # An N64 game (gcc 2.7.2 -O2 -fno-schedule-insns): `i * 3`, the base's `lw`, then `sll 2`.
    (f1, word), (f2, pointer) = c.variants(SOURCE, 'f')
    assert f1 == f2 == 'call_index_staging'
    assert '''        temp_index = i * 0x3;
        temp_base = M2C_FIELD(arg0, s32 *, 0);
        M2C_FIELD(arg0, s32 (**)(s32, s32), 4)(temp_base + temp_index * 4, ''' in word
    assert '    s32 temp_index;\n    s32 temp_base;\n' in word
    assert 'temp_base = M2C_FIELD(arg0, s32 **, 0);' in pointer and '(temp_base + temp_index, ' in pointer
    assert '    s32 *temp_base;\n' in pointer


def test_left_alone():
    def none(source):
        return c.variants(source, 'f') == []
    assert none(SOURCE.replace('i * 0xC', 'i * 4'))  # nothing to split
    assert none(SOURCE.replace('i * 0xC', 'i * 6'))  # not whole words
    assert none(SOURCE.replace('s32 *, 0)', 's16 *, 0)'))  # not a word-sized base
    assert none(SOURCE.replace('== i);', '== k(i));'))  # another argument calls a function
    assert none(SOURCE.replace('== i);', '== i++);'))
    assert none(SOURCE.replace('        M2C_FIELD(arg0, s32 (**)(s32, s32), 4)(', '        x = M2C_FIELD(arg0, s32 (**)(s32, s32), 4)('))


def test_propose_finds_the_family():
    from decomprepair.propose import propose
    assert any(p.module == 'call_index_staging_repairs' for p in propose(SOURCE, 'f').proposals)
