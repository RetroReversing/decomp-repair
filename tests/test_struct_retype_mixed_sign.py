from decomprepair import struct_retype_raw_offsets

SOURCE = """void copy(void *obj, void *from) {
    M2C_FIELD(obj, s16 *, 0xC) = 0x40;
    M2C_FIELD(obj, s32 *, 0x10) = gCount;
    M2C_FIELD(from, u16 *, 0xC) = (u16) M2C_FIELD(obj, u16 *, 0xC);
    M2C_FIELD(from, s32 *, 0x20) = M2C_FIELD(obj, s16 *, 0xC) + M2C_FIELD(obj, u16 *, 0xC);
}
"""


def texts(source):
    return [text for _, text in struct_retype_raw_offsets.variants(source, 'copy')]


def test_one_member_for_both_signs_with_the_other_reads_cast():
    both = texts(SOURCE)[-1]
    assert 'u16 fC;' in both and 'M2C_FIELD(obj' not in both
    assert '((PtrRec_obj *) obj)->fC = 0x40;' in both
    assert '((s16) ((PtrRec_obj *) obj)->fC) + ((PtrRec_obj *) obj)->fC' in both


def test_the_raw_offset_child_is_still_offered():
    assert any('M2C_FIELD(obj, u16 *, 0xC)' in text and 'PtrRec' in text for text in texts(SOURCE))


def test_an_updated_mixed_offset_stays_raw():
    updated = SOURCE.replace('M2C_FIELD(obj, s16 *, 0xC) = 0x40;', 'M2C_FIELD(obj, s16 *, 0xC) += 0x40;')
    assert all('fC;' not in text.split('PtrRec_obj;')[0] for text in texts(updated) if 'PtrRec_obj;' in text)
