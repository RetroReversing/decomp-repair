from decomprepair import store_run_order as module
from decomprepair.store_run_order import FAMILY, FAMILY_CONSTANT, LIMIT, variants

M2C = """extern M2C_UNK func_8002F8D0;
void *alloc(M2C_UNK, s32);
s32 f(void *arg0) {
    void *p;

    p = alloc(1, 2);
    M2C_FIELD(p, M2C_UNK **, 0x98) = &func_8002F8D0;
    M2C_FIELD(p, s32 *, 0x64) = 0xC8;
    M2C_FIELD(p, s32 *, 0x60) = (s32) D_800BD170;
    M2C_FIELD(p, s32 *, 0x70) = g(5);
    M2C_FIELD(p, s32 *, 0x68) = 0xE;
    M2C_FIELD(p, s32 *, 0x5C) = 0xFF;
    M2C_FIELD(p, s32 *, 0x64) = 0xC8;
    g(p);
    return (s32) p;
}
"""


def children(source, family=FAMILY, header=''):
    return [text for kind, text in variants(source, 'f', header) if kind == family]


def test_an_address_store_and_a_constant_store_swap_in_the_m2c_spelling():
    first = children(M2C)[0]
    assert first.index('0x64) = 0xC8;') < first.index('0x98) = &func_8002F8D0;')
    assert first.count('0x64) = 0xC8;') == 2 and first.index('0x98') < first.index('0x60')


def test_a_global_read_and_a_call_are_barriers():
    for text in children(M2C):
        # `0x60 = D_800BD170` reads a global and `0x70 = g(5)` calls: nothing crosses either of them
        assert text.index('0x98') < text.index('0x60') < text.index('0x70') < text.index('0x68')
        assert text.index('0x70') < text.index('0x5C') < text.index('g(p)')


def test_the_record_spelling_and_a_local_read_through_the_same_base_move_with_the_stores():
    source = """typedef struct { s32 v; } Field_s32;
s32 f(void *arg0) {
    void *p;
    s32 q;
    p = alloc(0x90);
    (((Field_s32 *) (((char *) p) + 0x5C))->v) = 0x62;
    q = (((Field_s32 *) (((char *) p) + 0x94))->v) / 3;
    (((Field_s32 *) (((char *) p) + 0x68))->v) = 0xE;
    (((Field_s32 *) (((char *) p) + 0))->v) = 0x117;
    (((Field_s32 *) (((char *) p) + 0x94))->v) = q;
    return (s32) p;
}
"""
    found = children(source)
    assert found
    swapped = [t for t in found if t.index('0x68') > t.index(') = 0x117;')]
    assert swapped and all(t.index('q = (((Field_s32') < t.index('->v) = q;') for t in found)
    # the read of cell 0x94 never passes the store back to it, and the store of q never passes its local
    assert all(t.index('0x94))->v) / 3;') < t.index('0x94))->v) = q;') for t in found)


def test_a_store_does_not_pass_a_read_of_its_cell_or_a_store_through_another_base():
    source = """s32 f(s32 *arg0) {
    void *p;
    s32 a;
    p = alloc(1);
    a = M2C_FIELD(p, s32 *, 8);
    M2C_FIELD(p, s32 *, 8) = 3;
    M2C_FIELD(arg0, s32 *, 0) = 5;
    M2C_FIELD(p, s32 *, 0xC) = 7;
    return a;
}
"""
    for text in children(source):
        assert text.index('a = M2C_FIELD(p, s32 *, 8);') < text.index('M2C_FIELD(p, s32 *, 8) = 3;')
        assert text.index('M2C_FIELD(arg0, s32 *, 0) = 5;') < text.index('= 7;') or text.index('= 3;') < text.index('= 7;')


def test_overlapping_cells_of_different_widths_do_not_swap():
    source = """void f(void *p) {
    M2C_FIELD(p, s32 *, 4) = 1;
    M2C_FIELD(p, s16 *, 6) = 2;
    M2C_FIELD(p, s16 *, 8) = 3;
}
"""
    for text in children(source):
        assert text.index('s32 *, 4') < text.index('s16 *, 6')


def test_volatile_and_asm_functions_get_nothing():
    assert not variants(M2C.replace('void *p;', 'volatile s32 z;\n    void *p;'), 'f')


def test_a_constant_stored_twice_becomes_a_local():
    found = children(M2C, FAMILY_CONSTANT)
    assert found
    one = found[0]
    assert 's32 k_C8;' in one and 'k_C8 = 200;' in one and one.count('= k_C8;') == 2
    assert one.index('s32 k_C8;') < one.index('p = alloc')
    # a constant stored once, or zero, is left alone
    single = M2C.replace('    M2C_FIELD(p, s32 *, 0x64) = 0xC8;\n    g(p);', '    g(p);')
    assert not [t for t in children(single, FAMILY_CONSTANT) if 'k_C8' in t and t.count('= k_C8;') > 1]
    assert not children('void f(void *p) {\n    M2C_FIELD(p, s32 *, 0) = 0;\n    M2C_FIELD(p, s32 *, 4) = 0;\n    g(p);\n}\n', FAMILY_CONSTANT)


def test_children_are_bounded_and_differ_from_the_source():
    body = ''.join(f'    M2C_FIELD(p, s32 *, {4 * k}) = {k + 3};\n' for k in range(30))
    source = f'void f(void *p) {{\n{body}}}\n'
    found = children(source)
    assert 0 < len(found) <= LIMIT and source not in found and len(set(found)) == len(found)


def test_it_declares_itself():
    assert module.REPAIR['variants'] is variants and set(module.REPAIR['families']) == {FAMILY, FAMILY_CONSTANT}
