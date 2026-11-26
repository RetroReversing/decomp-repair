"""mask_in_place: a local's mask written back into the local before the statement that reads it.

Synthetic shape of a 398-instruction SN64 GCC 2.8.1 glyph printer (1971 -> 330 with both blocks' masks in place)."""
from decomprepair import mask_in_place as s

SOURCE = '''void glyph(s32 idx, u8 ch) {
    u8 *tex;
    s32 w;

    tex = gFont;
    tex += idx * 0xD0;
    put(0xFD900000, (u32)tex & ~7);
    w = gW * 4;
    put2((w & 0xFFF) << 12);
    if (ch >= 0xC0) {
        tex = gFont;
        tex += gAccent[ch - 0xC0] * 0xD0;
        put(0xFD900000, (u32)tex & ~7);
    }
}
'''


def _texts(source=SOURCE):
    return [text for family, text in s.variants(source, 'glyph') if family == s.FAMILY]


def test_pointer_and_integer_masks_and_the_combined_child():
    texts = _texts()
    assert any('    tex = (u8 *)((u32) tex & ~7);\n    put(0xFD900000, (u32) tex);' in t
               and 'put(0xFD900000, (u32)tex & ~7);' in t for t in texts)
    assert any('    w &= 0xFFF;\n    put2((w) << 12);' in t for t in texts)
    both = [t for t in texts if t.count('tex = (u8 *)((u32) tex & ~7);') == 2]
    assert len(both) == 1 and '(u32)tex & ~7' not in both[0]


def test_a_local_read_after_the_statement_or_named_twice_declines():
    live = SOURCE.replace('    if (ch >= 0xC0) {', '    keep(w);\n    if (ch >= 0xC0) {')
    assert not any('w &= 0xFFF' in t for t in _texts(live))
    twice = SOURCE.replace('put2((w & 0xFFF) << 12);', 'put3((w & 0xFFF) << 12, w);')
    assert not any('w &= 0xFFF' in t for t in _texts(twice))


def test_an_operand_inside_a_larger_expression_declines():
    inside = SOURCE.replace('put2((w & 0xFFF) << 12);', 'put2(w & 0xFFF << 12);')
    assert not any('w &= 0xFFF' in t for t in _texts(inside))
