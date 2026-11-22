from decomprepair.widened_field_read_repairs import FAMILY, variants

SOURCE = '''void f(void *rec)
{
    if (((s32) M2C_FIELD(rec, u16 *, -0x10) == 0) && (M2C_FIELD(rec, u16 *, -0xC) == 0)) {
        go();
    }
    use((s32) M2C_FIELD(rec, u16 *, 4));
    if ((u32) M2C_FIELD(M2C_FIELD(rec, void **, 8), s16 *, 2) != 0) {
        go();
    }
    if ((s32) M2C_FIELD(rec, u8 *, 1) == 0) {
        go();
    }
}
'''


def test_a_halfword_cast_and_compared_is_read_as_a_word_at_the_same_offset():
    texts = [text for family, text in variants(SOURCE, 'f') if family == FAMILY]
    assert len(texts) == 2
    assert 'if (M2C_FIELD(rec, s32 *, -0x10) == 0) &&' not in texts[0]
    assert '((M2C_FIELD(rec, s32 *, -0x10) == 0) && (M2C_FIELD(rec, u16 *, -0xC) == 0))' in texts[0]
    assert '(u32 *' not in texts[1] and 'M2C_FIELD(M2C_FIELD(rec, void **, 8), u32 *, 2) != 0' in texts[1]


def test_reads_that_are_only_passed_on_or_are_bytes_stay():
    texts = ' '.join(text for family, text in variants(SOURCE, 'f'))
    assert 'use((s32) M2C_FIELD(rec, u16 *, 4));' in texts
    assert '(s32) M2C_FIELD(rec, u8 *, 1) == 0' in texts
