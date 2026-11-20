from decomprepair.kmc_operand_repairs import variants

ADDRESS = [('r', 'addu $a0, $v0, $v1', 'addu $a0, $v1, $v0')]
FLOAT = [('r', 'lwc1 $f2, 0($a0)', 'lwc1 $f4, 4($a0)'),
         ('r', 'lwc1 $f4, 4($a0)', 'lwc1 $f2, 0($a0)'),
         (' ', 'c.lt.s $f2, $f4', 'c.lt.s $f2, $f4')]


def test_typed_index_and_pointer_sum_preserve_element_scaling():
    for expression in ('&base[i]', 'base + i'):
        source = f'short *f(short *base, unsigned int i) {{ return {expression}; }}'
        [(family, result)] = variants(source, 'f', '', ADDRESS)
        assert family == 'kmc_address_operand_order'
        assert '(short *)(((unsigned int)i * (unsigned int)sizeof(*base)) + (unsigned int)base)' in result
        assert not variants(source, 'f', '', FLOAT)
        assert not variants(source, 'f', '#define i next()', ADDRESS)


def test_fp_order_keeps_relational_meaning_and_requires_typed_reads():
    source = 'int f(float a, float b) { if (a <= b) return 1; return 0; }'
    [(family, result)] = variants(source, 'f', '', FLOAT)
    assert family == 'kmc_float_comparison_order'
    assert 'if (b >= a)' in result
    assert not variants(source.replace('float b', 'int b'), 'f', '', FLOAT)
    assert not variants(source.replace('a <= b', 'a++ <= b'), 'f', '', FLOAT)
    assert not variants(source, 'f', '', ADDRESS)
