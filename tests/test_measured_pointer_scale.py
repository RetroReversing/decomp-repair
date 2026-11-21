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


def test_word_lookup_drops_one_scale_with_a_matching_load_relocation():
    source = 'extern M2C_UNK words;\ns32 f(s32 i) { return *(&words + ((i & 255) * 4)); }'
    code = [
        'lui $at, %hi(words)',
        'addu $at, $at, $a0',
        'lw $v0, %lo(words)($at)',
    ]
    rows = SHIFT + [(' ', instruction, instruction) for instruction in code]
    [(family, fixed)] = variants(source, 'f', '', rows)
    assert family == 'measured_duplicate_word_scale'
    assert 'extern M2C_UNK words[];' in fixed
    assert 'return words[(i & 255)];' in fixed
    assert not variants(source, 'f', '', rows[:-1])
    assert not variants(source, 'f', '', [*rows, ('i', 'lw $v1, 4($a0)', 'lw $v1, 8($a0)')])
    assert not variants(source.replace('return ', '').replace('));',')) = i;'), 'f', '', rows)


def test_loop_table_reuses_a_relocated_base_loaded_before_the_index_shift():
    source = 'extern M2C_UNK table;\ns32 f(s32 i) { return *((i * 4) + &table); }'
    before = ['lui $t0, %hi(table)', 'addiu $t0, $t0, %lo(table)']
    after = ['addu $a0, $a0, $t0', 'lw $v0, ($a0)']
    rows = [(' ', text, text) for text in before] + SHIFT + [(' ', text, text) for text in after]
    assert 'return table[i];' in dict(variants(source, 'f', '', rows))['measured_duplicate_word_scale']
    rows.insert(2, (' ', 'move $t0, $t1', 'move $t0, $t1'))
    assert not variants(source, 'f', '', rows)


def test_shared_offset_scales_only_once_for_each_proven_read():
    source = '''
extern M2C_UNK first;
extern M2C_UNK second;
s32 f(s32 i) {
    s32 offset;
    offset = (i & 0xFF) << 5;
    return *(&first + offset) | *(&second + offset);
}
'''
    code = [
        'lui $at, %hi(first)', 'addu $at, $at, $a0', 'lw $v0, %lo(first)($at)',
        'lui $v1, %hi(second)', 'addu $v1, $v1, $a0', 'lw $v1, %lo(second)($v1)',
    ]
    rows = [('i', 'sll $a0, $a0, 5', 'sll $a0, $a0, 7')] + [(' ', text, text) for text in code]
    [(family, fixed)] = variants(source, 'f', '', rows)
    assert family == 'measured_duplicate_word_scale'
    assert 'offset = (i & 0xFF) << 3;' in fixed
    assert 'return first[offset] | second[offset];' in fixed
    assert not variants(source.replace('second + offset','second + i'), 'f', '', rows)
    assert not variants(source, 'f', '', rows[:-1])
