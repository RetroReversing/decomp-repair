import re

from decomprepair.global_store_counter_stage import FAMILY, variants

SOURCE = """s32 blit(Img *img, s32 x0, s32 y0, s32 x1, s32 y1) {
    s32 rows;
    s32 texw;
    s32 n;
    s32 strip;
    s32 offset;

    rows = img->h;
    texw = img->w;
    offset = 0;
    D_80107890 = y0 << 2;
    switch (img->fmt) {
    case 16:
        while (rows > 0) {
            n = rows;
            if (texw * rows > 0x800) {
                n = 0x800 / texw;
            }
            GFX(0xF2000000, (n - 1) << 2);
            rows -= n;
            offset += texw * (n << 1);
        }
        break;
    case 32:
        while (rows >= 2) {
            s32 m;
            m = rows;
            if (texw * rows > 0x200) {
                m = 0x200 / texw;
                n = (m * 4); strip = n / x1;
            }
            GFX(0xF2000000, m << 2);
            rows -= m - 1;
            D_80107890 += strip;
        }
        break;
    }
    return texw;
}
"""


def _flat(text):
    return re.sub(r'\s+', ' ', text)


def _children():
    return [text for family, text in variants(SOURCE, 'blit') if family == FAMILY]


def test_the_store_to_a_global_is_staged_in_the_counter_the_loops_assign_later():
    out = [_flat(text) for text in _children()]
    assert any('n = y0 << 2; D_80107890 = n; switch' in text and 's32 m;' in text for text in out)


def test_the_later_loop_counter_is_merged_and_its_scratch_use_of_the_counter_inlined_in_one_child():
    out = [_flat(text) for text in _children()]
    merged = [text for text in out if 'D_80107890 = n;' in text and 's32 m;' not in text]
    assert merged, out
    text = merged[0]
    assert 'n = 0x200 / texw; strip = (n * 4) / x1;' in text
    assert 'GFX(0xF2000000, n << 2); rows -= n - 1;' in text
    assert not re.search(r'\bm\b', text)


def test_a_counter_read_before_the_store_or_a_constant_store_is_left_alone():
    read_first = SOURCE.replace('    offset = 0;\n', '    offset = n;\n')
    assert not any('D_80107890 = n;' in text for family, text in variants(read_first, 'blit'))
    constant = SOURCE.replace('D_80107890 = y0 << 2;', 'D_80107890 = 0;')
    assert not any(family == FAMILY for family, text in variants(constant, 'blit'))


def test_a_block_that_reads_the_counter_some_other_way_keeps_its_own_counter():
    other = SOURCE.replace('n = (m * 4); strip = n / x1;', 'n = (m * 4); strip = n / x1 + n;')
    out = [_flat(text) for family, text in variants(other, 'blit') if family == FAMILY]
    assert out and all('s32 m;' in text for text in out)
