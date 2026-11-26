"""scaled_carrier_writeback: a scaled index written back into its source variable before the narrowed value is read.

Synthetic shape of a 63-instruction table lookup built with GCC 2.7.2 -O1 (25 -> 0)."""
from decomprepair import scaled_carrier_writeback as s

SOURCE = '''f32 look(void *obj, s32 row) {
    s32 var;
    s32 slot;

    var = row;
    if ((var & 0xFFFF) >= 5U) {
        var = 4;
    }
    var &= 0xFFFF;
    slot = ((var) * 6) & 0xFFFF;
    return ((f32 *) obj)[slot];
}
'''


def _texts(source):
    return [text for family, text in s.variants(source, 'look') if family == s.FAMILY]


def test_an_earlier_self_mask_becomes_the_split():
    assert any('    var_unscaled = var & 0xFFFF;\n    var = var_unscaled * 6;\n    slot = var & 0xFFFF;' in t
               and 'var &= 0xFFFF;' not in t and 's32 var_unscaled;' in t for t in _texts(SOURCE))


def test_a_mask_inside_the_product_and_a_parameter():
    source = SOURCE.replace('    var &= 0xFFFF;\n    slot = ((var) * 6) & 0xFFFF;',
                            '    slot = ((row & 0xFFFF) * 6) & 0xFFFF;').replace('var = row;', 'var = 0;')
    assert any('row_unscaled = row & 0xFFFF;\n    row = row_unscaled * 6;\n    slot = row & 0xFFFF;' in t
               for t in _texts(source))


def test_an_unmasked_product_also_offers_the_plain_write_back():
    source = SOURCE.replace('    var &= 0xFFFF;\n', '')
    texts = _texts(source)
    assert any('    var = var * 6;\n    slot = var & 0xFFFF;' in t and 'var_unscaled' not in t for t in texts)
    assert len(texts) == 2


def test_a_variable_read_later_or_narrower_declines():
    assert not _texts(SOURCE.replace('return ((f32 *) obj)[slot];', 'return ((f32 *) obj)[slot + var];'))
    assert not _texts(SOURCE.replace('    s32 var;', '    u16 var;'))
