from decomprepair.symbol_width_repairs import SIGNED_BYTE_LOAD, signed_byte_base_variants

SOURCE = """extern char D_1000[];
static inline s8 narrow(s8 value) { return value; }
s8 f(int offset) {
    s8 value;
    value = narrow(*((u16 *) (D_1000 + offset)));
    return value;
}"""
ROWS = [('i', 'lb $v1, %lo(D_1000)($v1)', 'lb $v0, %lo(D_1001)($v0)')]


def test_restore_measured_signed_byte_at_table_base():
    assert signed_byte_base_variants(SOURCE, 'f', ROWS) == [
        (SIGNED_BYTE_LOAD, SOURCE.replace('(u16 *)', '(s8 *)')),
    ]
    assert not signed_byte_base_variants(SOURCE, 'f', ROWS + ROWS)
    assert not signed_byte_base_variants(SOURCE.replace('return value;', 'return value + 1;', 1), 'f', ROWS)
    assert not signed_byte_base_variants(SOURCE, 'f', [('i', ROWS[0][1], 'lb $v0, %lo(D_1002)($v0)')])
    assert not signed_byte_base_variants(SOURCE, 'f', ROWS, '#define narrow(x) other(x)')
