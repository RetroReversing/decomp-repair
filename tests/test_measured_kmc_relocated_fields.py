from decomprepair.measured_kmc_relocated_fields import variants

RESOLVE = {'base': 0x1000, 'global_a': 0x1020, 'global_b': 0x1010}.get


def rows(lines, changes):
    return [(' ', line, line) for line in lines] + changes


def test_relocated_pointer_reload():
    source = '''extern int base;
void f(void *arg) {
    M2C_FIELD(M2C_FIELD(&base, void **, 0x20), s8 *, 0x2E) = 1;
    M2C_FIELD(M2C_FIELD(&base, void **, 0x20), s8 *, 0x2F) = (s8) ((s32) M2C_FIELD(arg, s32 *, 0x90) / 2);
}'''
    diff = rows(['lui $v1, %hi(global_a)', 'sb $v0, 47($a0)'] + ['nop'] * 7,
                [('<', 'lui $a0, %hi(global_a)', '')])
    result = variants(source, 'f', '', diff, RESOLVE)
    assert result[0][0] == 'measured_relocated_pointer_reloads'
    assert 'extern void *global_a;' in result[0][1]
    assert result[0][1].count('M2C_FIELD(global_a, s8 *') == 2
    assert not variants(source, 'f', '', diff, lambda _: 1)
    assert not variants(source, 'f', 'extern void *global_a;', diff, RESOLVE)


def test_relocated_byte_branch():
    source = '''void f(void *arg) {
    s32 v;
    if ((u8) M2C_FIELD(&base, u8 *, 0x20) >= 2U) {
        v = M2C_FIELD(arg, s32 *, 0xC);
        if (!(v & 6)) { M2C_FIELD(arg, s32 *, 0xC) = (s32) (v | 2); }
    } else { M2C_FIELD(&base, u8 *, 0x20) = (u8) (M2C_FIELD(&base, u8 *, 0x20) + 1); }
}'''
    diff = rows(['lui $v1, %hi(global_a)', 'sltiu $v0, $v1, 2'] + ['nop'] * 7,
                [('<', 'lui $at, %hi(global_a)', '')])
    result = variants(source, 'f', '', diff, RESOLVE)
    assert result[0][0] == 'measured_relocated_byte_branch'
    assert 'extern u8 global_a;' in result[0][1]
    assert not variants(source.replace('0x20', '0x21'), 'f', '', diff, RESOLVE)


def test_relocated_swap():
    source = '''void f(void) {
    s32 v;
    M2C_FIELD(&base, s32 *, 0x10) = (s32) M2C_FIELD(&base, s32 *, 0x20);
    v = M2C_FIELD(&base, s32 *, 0x10);
    M2C_FIELD(&base, s32 *, 0x20) = v;
}'''
    diff = rows(['lui $v1, %hi(global_b)', 'sw $v1, %lo(global_a)($at)'] + ['nop'] * 7,
                [('<', 'lui $v0, %hi(global_a)', '')])
    # Target order has the source word first.
    diff = [diff[-1]] + diff[:-1]
    result = variants(source, 'f', '', diff, RESOLVE)
    assert result[0][0] == 'measured_relocated_word_swap'
    assert 'v = global_b;' in result[0][1]
    assert 'global_b = global_a;' in result[0][1]
    assert not variants(source.replace('0x10', '0x20'), 'f', '', diff, RESOLVE)


def test_typed_table_base():
    source = '''s32 f(s32 index) {
    return M2C_FIELD(&base, s32 *, 0x20) + ((M2C_FIELD((M2C_FIELD(&base, s32 *, 0x20) + (index & 0xFFFF)), u8 *, 0x32) * 0x28) + 0x44);
}'''
    diff = rows(['lui $a1, %hi(global_a)', 'addiu $v0, $v0, 68'] + ['nop'] * 7,
                [('>', '', 'addiu $v1, $v1, 68')])
    result = variants(source, 'f', '', diff, RESOLVE)
    assert result[0][0] == 'measured_typed_table_base'
    assert 'void *__repair_table_base;' in result[0][1]
    assert 'return __repair_table_base +' in result[0][1]
    assert not variants(source, 'f', '', diff, lambda _: None)
