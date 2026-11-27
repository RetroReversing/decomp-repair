from decomprepair import guard_member_copy, registry

SOURCE = '''void f(void *arg0) {
    void *child;
    void *other;

    child = M2C_FIELD(arg0, s32 **, 0x48);
    M2C_FIELD(arg0, s16 *, 0x6A) = 0xFFFF;
    if (child != NULL) {
        M2C_FIELD(child, s16 *, 0x10) = 3;
    }
    other = M2C_FIELD(arg0, s32 **, 0x48);
    M2C_FIELD(arg0, s32 *, 0x1C) += 0xC;
    if (other != NULL) {
        M2C_FIELD(other, s32 *, 0x14) = 4;
    }
}
'''


def test_both_sites_then_each():
    children = [source for _, source in guard_member_copy.variants(SOURCE, 'f')]
    assert len(children) == 4
    assert 'void *other;' not in children[1]
    assert 'child = M2C_FIELD(arg0, s32 **, 0x48);\n        M2C_FIELD(child, s32 *, 0x14) = 4;' in children[1]
    assert ('''    M2C_FIELD(arg0, s16 *, 0x6A) = 0xFFFF;
    if (M2C_FIELD(arg0, s32 **, 0x48) != NULL) {
        child = M2C_FIELD(arg0, s32 **, 0x48);
        M2C_FIELD(child, s16 *, 0x10) = 3;''') in children[0]
    assert 'other = M2C_FIELD(arg0, s32 **, 0x48);\n        M2C_FIELD(other' in children[0]
    assert children[0].count('child = M2C_FIELD') == 1


def test_a_store_to_the_loaded_member_or_a_later_read_stops_it():
    overwritten = SOURCE.replace('s16 *, 0x6A) = 0xFFFF', 's32 *, 0x48) = 0')
    assert all('child = M2C_FIELD(arg0, s32 **, 0x48);\n        M2C_FIELD(child' not in source
               for _, source in guard_member_copy.variants(overwritten, 'f'))
    read_later = SOURCE.replace('    }\n    other =', '    }\n    use(child);\n    other =')
    assert len(guard_member_copy.variants(read_later, 'f')) == 1


def test_a_call_between_stops_it():
    called = SOURCE.replace('M2C_FIELD(arg0, s16 *, 0x6A) = 0xFFFF;', 'g();')
    assert len(guard_member_copy.variants(called, 'f')) == 1


def test_declared_for_the_caller():
    assert any(repair.module == 'guard_member_copy' for repair in registry.declared())
