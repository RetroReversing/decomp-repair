from decomprepair.measured_square_loads import variants

SOURCE = '''
#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
void square(void *in, void *out) {
    s32 a;
    s32 b;
    a = M2C_FIELD(in, s32 *, 0);
    M2C_FIELD(out, s32 *, 0) = (s32) (a * a);
    b = M2C_FIELD(in, s32 *, 4);
    M2C_FIELD(out, s32 *, 4) = (s32) (b * b);
}
'''
ROWS = [
    (' ', 'lw $v0, ($a0)', 'lw $v0, ($a0)'),
    ('>', '', 'nop'),
    (' ', 'mult $v0, $v0', 'mult $v0, $v0'),
    (' ', 'lw $v0, 4($a0)', 'lw $v0, 4($a0)'),
    ('>', '', 'nop'),
    (' ', 'mult $v0, $v0', 'mult $v0, $v0'),
]


def test_inline_squared_loads_with_matching_stalls():
    [(family, candidate)] = variants(SOURCE, 'square', '', ROWS)
    assert family == 'measured_square_loads'
    assert 'a = M2C_FIELD' not in candidate
    assert 'M2C_FIELD(in, s32 *, 0) * M2C_FIELD(in, s32 *, 0)' in candidate
    assert 'M2C_FIELD(in, s32 *, 4) * M2C_FIELD(in, s32 *, 4)' in candidate


def test_no_speculative_rewrites():
    for source, header, rows in [
        (SOURCE, '', []),
        (SOURCE.replace('void *in', 'volatile void *in'), '', ROWS),
        (SOURCE.replace('a = M2C_FIELD', 'if (in) a = M2C_FIELD'), '', ROWS),
        (SOURCE.replace('    b = M2C_FIELD', '    use(a);\n    b = M2C_FIELD'), '', ROWS),
        (SOURCE.replace('(*(type_ptr)', '(side_effect(), *(type_ptr)'), '', ROWS),
        (SOURCE, '#define in something_else', ROWS),
        (SOURCE, 'typedef volatile int s32;', ROWS),
    ]:
        assert variants(source, 'square', header, rows) == []
