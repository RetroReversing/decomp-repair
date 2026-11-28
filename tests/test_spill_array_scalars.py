from decomprepair import spill_array_scalars as repair

SOURCE = '''void f(void) {
    s32 sp10[3];
    s32 unksp17;
    sp10[0] = 0;
    sp10[1] = 0;
    sp10[2] = 0;
    if (x) {
        sp10[1] = 1;
    }
    M2C_FIELD(&flags, u8 *, 0) = unksp17;
}
'''


def test_splits_the_spill_array_after_naming_the_byte_reads():
    [(family, text)] = repair.variants(SOURCE, 'f')
    assert family == 'spill_array_scalars'
    assert 's32 sp10_0; s32 sp10_1; s32 sp10_2;' in text
    assert 'sp10_1 = 1;' in text and 'sp10[' not in text
    assert 'M2C_FIELD(&flags, u8 *, 0) = (u8) sp10_1;' in text


def test_keeps_an_array_that_is_indexed_by_a_variable_or_passed_on():
    for use in ('sp10[i] = 0;', 'g(sp10);', 'g(&sp10[1]);', 'sp10[3] = 0;'):
        source = 'void f(void) {\n    s32 sp10[3];\n    sp10[0] = 0;\n    ' + use + '\n}\n'
        assert repair.variants(source, 'f') == []
