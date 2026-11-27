from decomprepair import registry, table_sum_subscript

SOURCE = '''extern char T[];
void f(void *p) {
    s32 i;

    M2C_FIELD(p, u8 *, 0x71) = *(u8 *)(i + T);
    M2C_FIELD(p, u8 *, 0x72) = (u8) M2C_FIELD((i + T), u8 *, 1);
    M2C_FIELD(p, u8 *, 0x73) = (u8) *(u8 *)(T + i);
}
'''


def test_reads_become_subscripts():
    [(family, child)] = table_sum_subscript.variants(SOURCE, 'f')
    assert family == 'table_sum_subscript'
    assert 'extern u8 T[];' in child
    assert '0x71) = T[i];' in child
    assert '0x72) = T[i + 1];' in child
    assert '0x73) = T[i];' in child


def test_mixed_types_or_another_value_read_stop_it():
    assert not table_sum_subscript.variants(SOURCE.replace('(u8) *(u8 *)(T + i)', '*(s8 *)(T + i)'), 'f')
    direct = SOURCE.replace('    s32 i;\n', '    s32 i;\n\n    g(T[0]);\n')
    assert not table_sum_subscript.variants(direct, 'f')


def test_a_wide_read_is_left_alone():
    wide = 'extern char T[];\nvoid f(void) {\n    x = *(s32 *)(i + T);\n}\n'
    assert not table_sum_subscript.variants(wide, 'f')


def test_declared_for_the_caller():
    assert any(repair.module == 'table_sum_subscript' for repair in registry.declared())
