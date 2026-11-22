from decomprepair.product_shift_stage_repairs import MASKED_PRODUCT, variants

SOURCE = """unsigned f(unsigned arg) {
    unsigned offset;
    offset = (arg & 0xff) * 134;
    return offset;
}"""


def test_stages_mask_through_the_unsigned_destination():
    text, = [source for family, source in variants(SOURCE, 'f') if family == MASKED_PRODUCT]
    assert '{ offset = (arg & 0xff); offset *= 134; }' in text


def test_address_taken_destination_is_not_staged():
    source = SOURCE.replace('    offset =', '    take_address(&offset);\n    offset =')
    assert variants(source, 'f') == []


def test_does_not_stage_out_of_range_products():
    assert variants(SOURCE.replace('0xff', '0xffffffff'), 'f') == []
