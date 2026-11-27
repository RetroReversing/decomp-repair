from decomprepair import registry
from decomprepair.field_extract_scale_split import FAMILY, REPAIR, variants

SOURCE = """void glyph(u32 index, s32 *out) {
    s32 col;
    s32 row;
    index &= 0xFFFF;
    col = (index & 0xF) * 8;
    row = (index >> 4) * 8;
    out[0] = col;
    out[1] = row;
}
"""


def test_high_field_first_with_halfword_locals():
    family, child = variants(SOURCE, 'glyph')[0]
    assert family == FAMILY
    assert ('    row = index >> 4;\n    col = index & 0xF;\n    row *= 8;\n    col *= 8;\n    out[0] = col;'
            in child)
    assert 'u16 col;' in child and 'u16 row;' in child


def test_both_orders_with_and_without_retyping():
    children = [child for _, child in variants(SOURCE, 'glyph')]
    assert len(children) == 4
    assert any('col = index & 0xF;\n    row = index >> 4;' in c and 's32 col;' in c for c in children)


def test_shift_scale_and_cast_value():
    source = SOURCE.replace('(index & 0xF) * 8', '((u16) index & 0x1F) << 2').replace('(index >> 4) * 8',
                                                                                    '(index >> 5) << 2')
    child = variants(source, 'glyph')[0][1]
    assert 'row = index >> 5;' in child and 'col = index & 0x1F;' in child and 'col <<= 2;' in child


def test_mask_not_matching_the_shift_is_left_alone():
    assert variants(SOURCE.replace('>> 4', '>> 3'), 'glyph') == []


def test_declares_itself():
    assert REPAIR['families'] == (FAMILY,)
    assert FAMILY in {family for entry in registry.declared() for family in entry.families}
