from decomprepair.measured_pointer_scale import variants

SHIFT = [('i','sll $a0, $a0, 2','sll $a0, $a0, 4')]


def test_float_lookup_replaces_scalar_with_typed_array_when_target_loads_float():
    source = 'extern M2C_UNK table;\nf32 f(s32 arg) {\n    return *(&table + (((arg + 1) & 0xFF) * 4));\n}'
    rows = SHIFT + [('o','lwc1 $f0, %lo(table)($at)','cvt.s.w $f0, $f0')]
    [(family,text)] = variants(source,'f','',rows)
    assert family == 'measured_float_table_scale'
    assert 'extern f32 table[];' in text
    assert 'return table[(arg + 1) & 0xFF];' in text
    assert not variants(source,'f','extern volatile s32 table;',rows)
    assert not variants(source,'f','',rows[1:])


def test_stride_keeps_an_optional_staged_argument_and_rejects_other_scalar_uses():
    source = '''
extern M2C_UNK table;
void f(s32 n) {
    s32 i;
    s32 value;
    i = n * 0x44;
    *(&table + i) = n;
    value = M2C_FIELD(other, s32 *, 8);
    work(n, 0, value + (value & 1));
}
'''
    rows = SHIFT + [('r','andi $v0, $a2, 1','andi $a2, $a3, 1'),
                    ('r','addu $a2, $a2, $v0','addu $a2, $a3, $a2')]
    choices = dict(variants(source,'f','',rows))
    assert 'i = n * 17;' in choices['measured_word_stride']
    assert 'value = value + (value & 1);\n    work(n, 0, value);' in choices['measured_word_stride_call']
    assert not variants(source.replace('    work', '    keep(i);\n    work'),'f','',rows)
    assert 'measured_word_stride_call' not in dict(variants(source,'f','',SHIFT))
