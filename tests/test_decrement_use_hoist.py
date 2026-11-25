import re

from decomprepair.decrement_use_hoist import FAMILY, variants

SOURCE = """s32 strips(Img *img, s32 rows, s32 texw) {
    s32 n;
    s32 offset;
    s32 strip;

    offset = 0;
    strip = 1;
    while (rows >= 2) {
        n = rows;
        if (texw * rows > 0x200) {
            n = 0x200 / texw;
        }
        rows -= n - 1;
        n--;
        GFX(0xF2000000, (n << 2) & 0xFFF);
        D_80107890 += strip;
        offset += texw * (n << 2);
    }
    return offset;
}
"""


def _flat(text):
    return re.sub(r'\s+', ' ', text)


def test_an_update_reading_the_decremented_counter_moves_above_the_decrement():
    out = [_flat(text) for family, text in variants(SOURCE, 'strips') if family == FAMILY]
    assert any('offset += texw * ((n - 1) << 2); n--; GFX(' in text and text.count('offset +=') == 1 for text in out)


def test_globals_calls_and_names_assigned_in_between_keep_their_place():
    out = [_flat(text) for _, text in variants(SOURCE, 'strips')]
    assert not any('D_80107890 += strip; n--;' in text for text in out)
    reassigned = SOURCE.replace('        D_80107890 += strip;\n', '        texw = 3;\n')
    assert not any('((n - 1) << 2); n--;' in _flat(text) for _, text in variants(reassigned, 'strips'))
    called = SOURCE.replace('offset += texw * (n << 2);', 'offset += f(n);')
    assert not any('(n - 1)' in _flat(text) for _, text in variants(called, 'strips'))
