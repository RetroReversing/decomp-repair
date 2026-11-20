from decomprepair.measured_memory_order import variants


def test_comma_load_order_requires_same_base_offsets_and_unescaped_destinations():
    source = '''
void f(void *p) {
    f32 a, b;
    (a = M2C_FIELD(p, f32 *, 4), b = M2C_FIELD(p, f32 *, 8), use(a, b));
}
'''
    rows = [('r', 'lwc1 $f2, 8($s0)', 'lwc1 $f0, 4($s0)'),
            ('r', 'lwc1 $f0, 4($s0)', 'lwc1 $f2, 8($s0)')]
    expected = source.replace('a = M2C_FIELD(p, f32 *, 4), b = M2C_FIELD(p, f32 *, 8)',
                              'b = M2C_FIELD(p, f32 *, 8), a = M2C_FIELD(p, f32 *, 4)')
    assert variants(source, 'f', rows) == [('measured_comma_load_order', expected)]
    assert not variants(source.replace('f32 a', 'volatile f32 a'), 'f', rows)
    assert not variants(source.replace('use(a, b)', 'use(&a, b)'), 'f', rows)
    assert not variants(source.replace('*, 8', '*, 12'), 'f', rows)


def test_reset_moves_only_independent_local_across_direct_call():
    source = '''
void f(void) {
    u32 n;
#define ALIAS untouched
    n = 0;
    work(1);
    output(n);
#undef ALIAS
}
'''
    rows = [('o', '', 'move $s1, $zero'), ('o', '', 'jal work'),
            (' ', 'addiu $a2, $zero, 1', 'addiu $a2, $zero, 1'),
            ('o', 'jal work', ''), ('o', 'move $s1, $zero', '')]
    assert variants(source, 'f', rows) == [
        ('measured_call_reset_order', source.replace('n = 0;\n    work(1);', 'work(1);\n    n = 0;'))]
    assert not variants(source.replace('work(1)', 'work(n)'), 'f', rows)
    assert not variants(source.replace('work(1)', 'work(ALIAS)'), 'f', rows)
    assert not variants(source.replace('output(n)', 'output(&n)'), 'f', rows)
