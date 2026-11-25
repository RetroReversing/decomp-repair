import re

from decomprepair.local_read_fence import FAMILY, variants

SOURCE = """s32 build(Img *img, s32 x, s32 flags) {
    s32 off;
    s32 rows;
    s32 scale;
    u8 *data;

    scale = 1;
    data = img->data;
    off = 0;
    while (img->h > 0) {
        rows = img->h;
        GFX(0xFD100000, (u32)(data + off));
        GFX(0xF2000000, scale * rows);
        off += img->w * rows;
        img->h -= rows;
    }
    return off;
}
"""


def _flat(text):
    return re.sub(r'\s+', ' ', text)


def test_a_single_read_of_a_pointer_local_goes_through_a_fenced_scratch_copy():
    out = [_flat(text) for family, text in variants(SOURCE, 'build') if family == FAMILY]
    assert any('{ u8 *__fence_data; do { __fence_data = data; } while (0); GFX(0xFD100000, (u32)(__fence_data + off)); }'
               in text for text in out)
    assert any('do { do { __fence_data = data; } while (0); } while (0);' in text for text in out)


def test_the_assignment_of_the_local_and_non_pointer_locals_are_left_alone():
    out = [_flat(text) for _, text in variants(SOURCE, 'build')]
    assert out and all('data = img->data;' in text for text in out)
    assert not any('__fence_off' in text or '__fence_scale' in text or '__fence_rows' in text for text in out)


def test_nothing_is_offered_without_a_pointer_local():
    assert variants('s32 f(s32 a) { s32 b; b = a; g(b); return b; }', 'f') == []
