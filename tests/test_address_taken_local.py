import re

from decomprepair.address_taken_local import FAMILY, variants

SOURCE = """s32 blit(Img *img, s32 x0, s32 y0, s32 x1, s32 y1) {
    s32 texw;
    s32 dsdx;
    s32 dtdy;
    s32 rows;
    u8 *pixels;

    texw = img->w;
    rows = img->h;
    pixels = img->data;
    dsdx = (texw << 10) / (x1 - x0 + 1);
    dtdy = (texw << 10) / (y1 - y0 + 1);
    setup(0);
    switch (img->fmt) {
    case 16:
        while (rows > 0) {
            GFX(0xF1000000, (dsdx << 16) | (dtdy & 0xFFFF));
            rows -= 8;
        }
        break;
    case 32:
        while (rows > 0) {
            GFX(0xF1000000, (dsdx << 16) | (dtdy & 0xFFFF));
            rows -= 4;
        }
        break;
    }
    return texw;
}
"""


def _flat(text):
    return re.sub(r'\s+', ' ', text)


def test_a_once_assigned_scalar_read_in_both_arms_has_its_address_taken_before_its_assignment():
    out = [_flat(text) for family, text in variants(SOURCE, 'blit') if family == FAMILY]
    assert any('(void)&dsdx; dsdx = (texw << 10) / (x1 - x0 + 1);' in text for text in out)
    assert any('(void)&dtdy; dtdy =' in text for text in out)
    assert any('(void)&dsdx;' in text and '(void)&dtdy;' in text and '(void)&texw;' in text for text in out)


def test_pointers_reassigned_locals_and_locals_already_addressed_are_left_alone():
    out = [_flat(text) for _, text in variants(SOURCE, 'blit')]
    assert not any('(void)&pixels' in text or '(void)&rows' in text for text in out)
    taken = SOURCE.replace('    setup(0);', '    setup(&dsdx);')
    assert not any('(void)&dsdx' in _flat(text) for _, text in variants(taken, 'blit'))


def test_the_indentation_of_the_assignment_is_kept():
    out = [text for _, text in variants(SOURCE, 'blit')]
    assert any('\n    (void)&dsdx;\n    dsdx = ' in text for text in out)
