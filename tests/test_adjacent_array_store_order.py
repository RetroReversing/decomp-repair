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


def test_adjacent_stores_to_different_fields_of_one_array_are_swapped_on_one_line():
    from decomprepair.adjacent_array_store_order import variants
    source = ("void f(N *D, int n) {\n int i;\n for (i = 1; i < n; i++) { D[i].prev = &D[i - 1]; D[i - 1].next = &D[i]; }\n}\n")
    children = [child for _, child in variants(source, "f")]
    assert any("{ D[i - 1].next = &D[i]; D[i].prev = &D[i - 1]; }" in child for child in children)


def test_element_field_stores_that_load_call_or_share_a_field_stay_put():
    from decomprepair.adjacent_array_store_order import variants
    for body in ("D[i].a = D[j].b; D[i].c = 1;", "D[i].a = g(); D[i].c = 1;", "D[i].a = 1; D[j].a = 2;",
                 "D[i].a = *p; D[i].c = 1;"):
        assert variants("void f(N *D, int i, int j, int *p) { " + body + " }\n", "f") == []
