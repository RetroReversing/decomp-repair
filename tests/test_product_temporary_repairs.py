from decomprepair import product_temporary_repairs as product

SOURCE = '''extern char D_A[];
extern char D_B[];

s32 f(s32 arg0, s32 handle) {
    do {
        s32 idx = handle & 0xFF;
        arg0 = idx * 0x1a0;
        if (*(s32 *)(D_A + arg0) != handle) {
            return 0;
        }
        handle = *(s32 *)(D_B + idx * 0x1a0);
    } while (handle != -1);
    return 1;
}
'''


def test_repeated_offset_product_is_staged_in_a_block_local():
    out = product.variants(SOURCE, 'f')
    assert [family for family, _ in out] == ['product_temporary']
    text = out[0][1]
    assert '{ s32 __product = idx * 0x1a0; handle = *(s32 *)(D_B + __product); }' in text
    assert 'arg0 = idx * 0x1a0;' in text


def test_a_product_named_nowhere_else_is_left_alone():
    assert not product.variants(SOURCE.replace('arg0 = idx * 0x1a0;', 'arg0 = idx * 0x1a4;'), 'f')
