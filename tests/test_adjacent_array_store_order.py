from decomprepair.adjacent_array_store_order import FAMILY, variants

SOURCE = """
void build(void *p) {
    s16 spA58[3];
    s16 other[2];
    s32 x;
    x = M2C_FIELD(p, s16 *, 0x17C);
    spA58[1] = 0;
    spA58[2] = (u16) M2C_FIELD(p, s16 *, 0x17C);
    call(spA58);
}
"""


def test_swaps_two_consecutive_stores_to_one_local_array():
    [(family, revised)] = variants(SOURCE, 'build')
    assert family == FAMILY
    assert revised.index('spA58[2] =') < revised.index('spA58[1] = 0;')
    [(_, back)] = variants(revised, 'build')
    assert back == SOURCE


def test_skips_calls_other_arrays_and_same_index():
    assert variants(SOURCE.replace('(u16) M2C_FIELD(p, s16 *, 0x17C)', 'get(p)'), 'build') == []
    assert variants(SOURCE.replace('spA58[2] =', 'other[1] ='), 'build') == []
    assert variants(SOURCE.replace('spA58[2] =', 'spA58[1] ='), 'build') == []
    assert variants(SOURCE.replace('s16 spA58[3];', 's16 *spA58;'), 'build') == []
    assert variants(SOURCE.replace('= 0;', '= spA58[0];'), 'build') == []
