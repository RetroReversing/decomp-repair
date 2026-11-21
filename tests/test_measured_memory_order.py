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


def same(instruction):
    return (' ', instruction, instruction)


def test_lift_returned_objects_flags_before_publishing_a_relocated_pointer():
    source = '''
void f(void *arg) {
    void *p;
    p = lookup(arg);
    M2C_FIELD(&record, void **, 8) = p;
    M2C_FIELD(p, s32 *, 16) = (s32) (M2C_FIELD(p, s32 *, 16) | 4);
}
'''
    load = 'lw $v1, 16($v0)'
    rows = [
        same('jal lookup'), same('nop'),
        ('o', load, ''),
        same('lui $at, %hi(current)'), same('sw $v0, %lo(current)($at)'),
        ('o', '', load),
        same('ori $v1, $v1, 4'), same('sw $v1, 16($v0)'),
    ]
    symbols = {'record': 0x100, 'current': 0x108}
    [(family, fixed)] = variants(source, 'f', rows, resolve=symbols.get)
    assert family == 'measured_earlier_word_load'
    assert 's32 __repair_before_publish;' in fixed
    assert fixed.index('__repair_before_publish = M2C_FIELD') < fixed.index('M2C_FIELD(&record')
    assert 'M2C_FIELD(p, s32 *, 16) = __repair_before_publish | 4;' in fixed
    assert not variants(source, 'f', rows)
    assert not variants(source.replace('&record, void **, 8', '&record, void **, 12'), 'f', rows, resolve=symbols.get)
    assert not variants(source.replace('| 4', '| 8'), 'f', rows, resolve=symbols.get)
    assert not variants(source, 'f', rows[:-1], resolve=symbols.get)
    assert not variants(source, 'f', rows, resolve=symbols.get, header='#define __repair_before_publish 0')


def test_lift_previous_link_before_the_two_halfword_clears():
    source = '''
void f(void *node, void *queue) {
    M2C_FIELD(node, s32 *, 4) = 0;
    M2C_FIELD(node, s16 *, 8) = 0;
    M2C_FIELD(node, s16 *, 10) = 0;
    M2C_FIELD(node, void **, 0) = (void *) M2C_FIELD(queue, void **, 4);
    M2C_FIELD(queue, void **, 4) = node;
}
'''
    load = 'lw $v0, 4($a1)'
    rows = [
        same('sw $zero, 4($a0)'),
        ('o', load, ''),
        same('sh $zero, 8($a0)'), same('sh $zero, 0xa($a0)'),
        ('o', '', load),
        same('sw $v0, ($a0)'), same('jr $ra'), same('sw $a0, 4($a1)'),
    ]
    [(family, fixed)] = variants(source, 'f', rows)
    assert family == 'measured_earlier_word_load'
    assert ('M2C_FIELD(node, s32 *, 4) = 0;\n    __repair_previous_link = M2C_FIELD(queue, void **, 4);\n'
            '    M2C_FIELD(node, s16 *, 8) = 0;') in fixed
    assert 'M2C_FIELD(node, void **, 0) = __repair_previous_link;' in fixed
    assert not variants(source.replace('s16 *, 10', 's16 *, 12'), 'f', rows)
    assert not variants(source, 'f', rows[:-1] + [same('sw $a0, 8($a1)')])
    assert not variants(source, 'f', rows[:1] + [('o', '', load), *rows[2:4], ('o', load, ''), *rows[5:]])
