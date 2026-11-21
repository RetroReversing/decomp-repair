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


def test_repeated_word_table_requires_two_measured_reads_and_no_other_uses():
    source = """extern M2C_UNK table;
int scan(int index, int other) {
    return *(&table + (index * 4)) + *(&table + (other * 4));
}
"""
    access = [
        ('i', 'sll $v0, $v0, 2', 'sll $v0, $v0, 4'),
        (' ', 'lui $at, %hi(table)', 'lui $at, %hi(table)'),
        (' ', 'addu $at, $at, $v0', 'addu $at, $at, $v0'),
        (' ', 'lw $v0, %lo(table)($at)', 'lw $v0, %lo(table)($at)'),
    ]
    [(family, candidate)] = variants(source, 'scan', '', access * 2)
    assert family == 'measured_repeated_word_table'
    assert 'extern M2C_UNK table[];' in candidate
    assert 'return table[index] + table[other];' in candidate
    assert not variants(source, 'scan', 'extern int table;', access * 2)
    assert not variants(source.replace('return ', 'observe(&table); return '), 'scan', '', access * 2)
    assert not variants(source, 'scan', '', access + [(' ', 'nop', 'nop')] * 2)


def test_halfword_byte_cursor_uses_the_measured_back_edge_step():
    source = """int f(void *record) {
    char *cursor;
    cursor = (*(u16 **)((char *)record + 4));
    do {
        use(*(u16 *)cursor);
        cursor += 3;
    } while (again());
}"""
    rows = [
        (' ', 'move $s4, $a0', 'move $s4, $a0'),
        (' ', 'lhu $a0, ($s4)', 'lhu $a0, ($s4)'),
        ('|', 'bnez $v0, 4 [bytes 1440fffe]', 'bnez $v0, 4 [bytes 1440fffd]'),
        ('i', 'addiu $s4, $s4, 6', 'addiu $s4, $s4, 3'),
    ]
    [(family, candidate)] = variants(source, 'f', '', rows)
    assert family == 'measured_halfword_byte_cursor'
    assert 'cursor += 6;' in candidate
    assert not variants(source.replace('*(u16 *)cursor', '*cursor'), 'f', '', rows)
    assert not variants(source, 'f', '', [rows[0], (' ', 'lbu $a0, ($s4)', 'lbu $a0, ($s4)'), *rows[2:]])


def test_repeated_word_table_accepts_a_direct_calls_argument_in_its_delay_slot():
    source = """
extern M2C_UNK table;
void f(s32 one, s32 two) {
    observe(*(&table + (one * 4)));
    inspect(*(&table + (two * 4)));
}
"""
    def same(op):
        return (' ', op, op)
    access = [
        ('i', 'sll $v0, $v0, 2', 'sll $v0, $v0, 4'),
        same('lui $a0, %hi(table)'),
        same('addu $a0, $a0, $v0'),
        same('lw $a0, %lo(table)($a0)'),
    ]
    rows = access + access[:3] + [same('jal inspect'), access[-1]]
    [(family, fixed)] = variants(source, 'f', '', rows)
    assert family == 'measured_repeated_word_table'
    assert 'observe(table[one]);' in fixed
    assert 'inspect(table[two]);' in fixed
    assert not variants(source, 'f', '', rows[:-1] + [same('lw $s0, %lo(table)($a0)')])
    assert not variants(source, 'f', '', rows[:-1] + [same('lw $a0, %lo(other)($a0)')])


def test_measured_stride_in_halfword_return_keeps_odd_factor():
    source = 'extern M2C_UNK slots;\ns32 f(s32 i) { return ((u16)*(&slots + (i * 12)) >> 7) & 1; }'
    rows = [
        ('i', 'sll $v0, $v0, 2', 'sll $v0, $v0, 4'),
        ('i', 'lui $at, %hi(slots)', 'lui $at, %hi(other)'),
        (' ', 'addu $at, $at, $v0', 'addu $at, $at, $v0'),
        ('i', 'lhu $v0, %lo(slots)($at)', 'lhu $v0, %lo(other)($at)'),
    ]
    [(family, trial)] = variants(source, 'f', '', rows)
    assert family == 'measured_relocated_array_scale'
    assert 'extern u8 slots[];' in trial
    assert '*(u16 *)(slots + i * 12)' in trial
    assert not variants(source.replace('i * 12', 'i * 6'), 'f', '', rows)


def test_measured_float_table_with_float_index_parameter():
    source = 'extern M2C_UNK samples;\nf32 f(f32 x) { return *(&samples + (((s32) x & 0xfff) * 4)); }\n'
    rows = [
        ('i', 'sll $v0, $v0, 2', 'sll $v0, $v0, 4'),
        (' ', 'lui $at, %hi(samples)', 'lui $at, %hi(samples)'),
        (' ', 'addu $at, $at, $v0', 'addu $at, $at, $v0'),
        ('o', '', 'lwc1 $f0, %lo(samples)($at)'),
        (' ', 'jr $ra', 'jr $ra'),
        ('o', 'lwc1 $f0, %lo(samples)($at)', 'cvt.s.w $f0, $f0'),
    ]
    [(family, trial)] = variants(source, 'f', '', rows)
    assert family == 'measured_float_table_scale'
    assert 'extern f32 samples[];' in trial
    assert 'return samples[(s32)x & 0xfff];' in trial


def test_measured_halfword_argument_with_displaced_byte_pointer():
    source = 'void f(s32 n, u16 *packet) { work(n & 0xffff, packet + 4, *packet); }\n'
    rows = [
        (' ', 'lhu $a2, ($a1)', 'lhu $a2, ($a1)'),
        (' ', 'andi $a0, $a0, 0xffff', 'andi $a0, $a0, 0xffff'),
        (' ', 'jal work', 'jal work'),
        ('i', 'addiu $a1, $a1, 4', 'addiu $a1, $a1, 8'),
    ]
    assert variants(source, 'f', '', rows) == [
        ('measured_call_byte_offset', source.replace('packet + 4', '(u8 *)packet + 4'))
    ]
    assert not variants(source.replace('packet + 4', 'packet + 3'), 'f', '', rows)
    assert not variants(source, 'f', '', rows[1:])


def test_float_lookup_preserves_a_bias_after_converting_the_parameter():
    source = ('extern M2C_UNK table;\nf32 f(f32 x) {\n'
              '    return *(&table + ((((s32) x - 0x100) & 0xFFF) * 4));\n}')
    rows = SHIFT + [('o', 'lwc1 $f0, %lo(table)($at)', 'cvt.s.w $f0, $f0')]
    assert dict(variants(source, 'f', '', rows))['measured_float_table_scale'] == (
        'extern f32 table[];\nf32 f(f32 x) {\n    return table[((s32) x - 0x100) & 0xFFF];\n}'
    )
    assert not variants(source.replace('0x100', 'bias'), 'f', '', rows)
