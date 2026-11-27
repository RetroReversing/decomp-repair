"""adjacent_halfword_fields: `(s16) word@N` beside `s16@N` becomes the pair of halfwords N and N+2.

Reduced from a KMC N64 position/velocity update (score 20 -> 0): the `pair` child is the matched source's two lines."""
from decomprepair import adjacent_halfword_fields as a

SOURCE = '''void f(void *arg0) {
    M2C_FIELD(arg0, s32 *, 0) = (s32) ((s16) M2C_FIELD(arg0, s32 *, 0x30) + M2C_FIELD(arg0, s32 *, 0));
    M2C_FIELD(arg0, s32 *, 4) = (s32) (M2C_FIELD(arg0, s16 *, 0x30) + M2C_FIELD(arg0, s32 *, 4));
}
'''


def _by_family(source=SOURCE):
    return {family: text for family, text in a.variants(source, 'f')}


def test_pair_reads_the_two_neighbouring_halfwords_in_turn():
    text = _by_family()[a.PAIR]
    assert 'M2C_FIELD(arg0, s16 *, 0x30) + M2C_FIELD(arg0, s32 *, 0)' in text
    assert 'M2C_FIELD(arg0, s16 *, 0x32) + M2C_FIELD(arg0, s32 *, 4)' in text
    assert '(s16) M2C_FIELD' not in text


def test_narrow_only_names_the_low_half_the_narrowed_word_already_read():
    text = _by_family()[a.FAMILY]
    assert 'M2C_FIELD(arg0, s16 *, 0x32) + M2C_FIELD(arg0, s32 *, 0)' in text
    assert 'M2C_FIELD(arg0, s16 *, 0x30) + M2C_FIELD(arg0, s32 *, 4)' in text


def test_no_halfword_twin_no_variant():
    assert _by_family(SOURCE.replace('s16 *, 0x30', 's16 *, 0x40')) == {}
