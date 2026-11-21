from decomprepair.measured_float_grid_stores import variants

SOURCE = """void f(const struct Input *p, float grid[3][3]) {
    volatile double pad[1];
    float x = p->x;
    float y = p->y;
    float xy = x * y;
    float a = x + xy;
    float b = y + xy;
    float c = x - xy;
    float d = y - xy;
    grid[0][0] = 1.0f - a;
    grid[0][1] = b;
    grid[1][0] = c;
    grid[0][2] = d;
    grid[1][1] = x;
    grid[1][2] = y;
    grid[2][1] = xy;
    grid[2][0] = x;
    grid[2][2] = xy;
}
"""

ROWS = [('i', 'swc1 $f4, 8($a1)', 'swc1 $f4, 0xc($a1)')]


def test_float_grid_bundles_store_order_expression_lifetimes_and_operand_order():
    [(family, first), (_, second)] = variants(SOURCE, 'f', ROWS)
    assert family == 'measured_float_grid_stores'
    assert 'volatile double pad' not in first
    assert 'grid[0][0] = 1.0f - (x + xy);' in first
    assert 'grid[0][2] = (y - xy);\n    grid[1][0] = (x - xy);' in first
    assert second == first.replace('float xy = x * y;', 'float xy = y * x;')


def test_float_grid_requires_independent_local_values_and_target_evidence():
    assert not variants(SOURCE, 'f', [])
    assert not variants(SOURCE.replace('float b = y + xy;', 'float b = compute();'), 'f', ROWS)
    assert not variants(SOURCE.replace('grid[2][2] = xy;', 'grid[2][2] = grid[1][1];'), 'f', ROWS)
    assert not variants(SOURCE.replace('grid[2][2]', 'grid[2][0]'), 'f', ROWS)


def test_float_grid_retries_products_after_stores_align():
    [(_, normalized), (_, exact_shape)] = variants(SOURCE, 'f', ROWS)
    registers = [('r', 'mul.s $f2, $f4, $f6', 'mul.s $f2, $f6, $f4')]
    assert variants(normalized, 'f', registers) == [('measured_float_grid_stores', exact_shape)]
