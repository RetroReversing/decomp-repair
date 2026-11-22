from decomprepair.measured_matrix_products import variants

SOURCE = '''
#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
void f(void *cells, void *factors) {
    M2C_FIELD(cells, s16 *, 0) = (s16) ((u32) (M2C_FIELD(cells, s16 *, 0) * M2C_FIELD(factors, s32 *, 0)) >> 12);
    M2C_FIELD(cells, s16 *, 2) = (s16) ((u32) (M2C_FIELD(cells, s16 *, 2) * M2C_FIELD(factors, s32 *, 4)) >> 12);
}
'''
ROWS = [
    ('r', 'lh $v1, ($a2)', 'lh $v0, ($a2)'),
    ('r', 'lw $v0, ($a1)', 'lw $v1, ($a1)'),
    ('r', 'mult $v1, $v0', 'mult $v0, $v1'),
    ('r', 'lh $v1, 2($a2)', 'lh $v0, 2($a2)'),
]


def test_stage_each_product_in_one_local():
    [(family, candidate)] = variants(SOURCE, 'f', '', ROWS)
    assert family == 'measured_matrix_products'
    assert candidate.count('s32 __repair_product;') == 1
    assert candidate.count('__repair_product = __repair_product *') == 2
    assert '__repair_product = M2C_FIELD(cells, s16 *, 0); __repair_product =' in candidate


def test_decline_unproven_or_unsafe_shapes():
    for source, header, rows in [
        (SOURCE, '', []),
        (SOURCE.replace('void *cells', 'volatile void *cells'), '', ROWS),
        (SOURCE.replace('    M2C_FIELD(cells, s16 *, 0)', '    if (cells) M2C_FIELD(cells, s16 *, 0)'), '', ROWS),
        (SOURCE.replace('M2C_FIELD(cells, s16 *, 2) *', 'M2C_FIELD(cells, s16 *, 6) *'), '', ROWS),
        (SOURCE, '#define cells call()', ROWS),
        (SOURCE, 'typedef volatile int s32;', ROWS),
        (SOURCE.replace('(*(type_ptr)', '(side_effect(), *(type_ptr)'), '', ROWS),
    ]:
        assert variants(source, 'f', header, rows) == []
