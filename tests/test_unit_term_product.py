from decomprepair.unit_term_product import FAMILY, variants

SOURCE = '''void func_80000000(void)
{
    f32 x, y, sy;
    s32 n, m;
    use(x * sy, y * sy + sy);
    use(sy * x + sy, n * m + m);
}
'''


def test_a_factor_added_back_moves_inside_the_product():
    found = variants(SOURCE, 'func_80000000')
    assert [family for family, _ in found] == [FAMILY] * 3
    both = found[0][1]
    assert 'use(x * sy, (y + 1.0f) * sy);' in both
    assert 'use((x + 1.0f) * sy, n * m + m);' in both


def test_only_plain_floats_and_whole_terms():
    assert not variants(SOURCE.replace('f32 x, y, sy;', 's32 x, y, sy;'), 'func_80000000')
    for term in ('y * sy + sy * x', 'y * sy + sy.z', 'x / y * sy + sy', 'y * sy + syz'):
        assert not variants(f'void f(f32 y, f32 sy) {{ use({term}); }}', 'f'), term
