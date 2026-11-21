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


def test_typed_cursor_uses_element_step_when_only_delay_slot_is_scaled_twice():
    source = '''
void f(s32 *arg, s32 count) {
    s32 *cursor;
    cursor = arg;
    do {
        *cursor += 7;
        cursor += 4;
    } while (--count > 0);
}
'''
    loop = [
        'move $v0, $zero',
        'lw $t0, ($a0)',
        'addiu $t0, $t0, 7',
        'sw $t0, 0($a0)',
        'bnez $v0, 0x4',
    ]
    rows = [(' ', op, op) for op in loop] + [('i', 'addiu $a0, $a0, 4', 'addiu $a0, $a0, 0x10')]
    [(family, repaired)] = variants(source, 'f', '', rows)
    assert family == 'measured_pointer_step'
    assert repaired == source.replace('cursor += 4;', 'cursor += 1;')

    assert not variants(source.replace('s32 *cursor;', 'u8 *cursor;'), 'f', '', rows)
    assert not variants(source.replace('*cursor += 7;', 'x += 7;'), 'f', '', rows)
    assert not variants(source.replace('cursor = arg;', 'escape(&cursor);'), 'f', '', rows)
    assert not variants(source, 'f', '', rows + [('i', 'li $v0, 1', 'li $v0, 2')])
    assert not variants(source, 'f', '', rows[:4] + [(' ', 'bnez $v0, 16', 'bnez $v0, 16')] + rows[-1:])
    assert not variants(source, 'f', '', rows[:3] + [(' ', 'sw $t0, ($a1)', 'sw $t0, ($a1)')] + rows[-2:])


def test_duplicated_scale_recovers_signed_halfword_array_at_target_relocation():
    source = 'extern M2C_UNK wave;\ns16 f(s32 i) { return *(&wave + ((i & 255) * 2)); }'
    rows = [
        ('i', 'sll $a0, $a0, 1', 'sll $a0, $a0, 3'),
        ('i', 'lui $at, %hi(wave)', 'lui $at, %hi(D_80001236)'),
        (' ', 'addu $at, $at, $a0', 'addu $at, $at, $a0'),
        (' ', 'jr $ra', 'jr $ra'),
        ('i', 'lh $v0, %lo(wave)($at)', 'lh $v0, %lo(D_80001236)($at)'),
    ]
    [(family, fixed)] = variants(source, 'f', '', rows)
    assert family == 'measured_relocated_array_scale'
    assert 'extern s16 wave[];' in fixed
    assert 'return wave[(i & 255)];' in fixed
    assert not variants(source, 'f', 'extern s32 wave;', rows)
    assert not variants(source, 'f', '', rows[:-1] + [('i', rows[-1][1], 'lh $v0, %lo(other)($at)')])


def test_byte_array_keeps_record_stride_when_the_high_relocation_rounds_to_same_value():
    source = 'extern M2C_UNK bytes;\nu8 f(s32 i) { return *(&bytes + ((i & 65535) * 0x64)); }'
    rows = [
        ('i', 'sll $a0, $a0, 2', 'sll $a0, $a0, 4'),
        (' ', 'lui $at, %hi(bytes)', 'lui $at, %hi(D_80001233)'),
        (' ', 'addu $at, $at, $a0', 'addu $at, $at, $a0'),
        ('i', 'lbu $v0, %lo(bytes)($at)', 'lbu $v0, %lo(D_80001233)($at)'),
    ]
    [(family, fixed)] = variants(source, 'f', '', rows)
    assert family == 'measured_relocated_array_scale'
    assert 'extern u8 bytes[];' in fixed
    assert 'return bytes[(i & 65535) * 0x64];' in fixed
    assert not variants(source.replace('0x64', '0x68'), 'f', '', rows)


def test_both_halves_of_a_sentinel_scan_drop_explicit_byte_scaling():
    source = '''
void f(u16 *data) {
    s32 n = 0;
    do { n += 1; } while (*(((n & 0xFFFF) * 2) + data) != 65535);
    do { n -= 1; } while (*(((n & 0xFFFF) * 2) + data) == 0);
}
'''
    chunk = [
        (' ', 'andi $v0, $a2, 0xffff', 'andi $v0, $a2, 0xffff'),
        ('i', 'sll $v0, $v0, 1', 'sll $v0, $v0, 2'),
        (' ', 'addu $v0, $v0, $a0', 'addu $v0, $v0, $a0'),
        (' ', 'lhu $v0, ($v0)', 'lhu $v0, ($v0)'),
    ]
    rows = (chunk + [(' ', 'bnel $v0, $v1, 0', 'bnel $v0, $v1, 0')]
            + chunk + [(' ', 'beql $v0, $zero, 20', 'beql $v0, $zero, 20')])
    [(family, fixed)] = variants(source, 'f', '', rows)
    assert family == 'measured_halfword_scan_scale'
    assert fixed.count('*((n & 0xFFFF) + data)') == 2
    assert not variants(source, 'f', '', rows[:-1])
    assert not variants(source.replace('== 0', '= 0'), 'f', '', rows)
