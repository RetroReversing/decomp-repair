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


def test_halfword_lookup_in_call_delay_slot_keeps_nested_index_and_byte_stride():
    source = ('extern M2C_UNK entries;\n'
              'void f(void) { consume(*(&entries + (select(3) * 12))); }')
    rows = [
        ('i', 'sll $v0, $v0, 2', 'sll $v0, $v0, 4'),
        ('i', 'lui $a0, %hi(entries)', 'lui $a0, %hi(entries+0x2)'),
        (' ', 'addu $a0, $a0, $v0', 'addu $a0, $a0, $v0'),
        (' ', 'jal consume', 'jal consume'),
        ('i', 'lhu $a0, %lo(entries)($a0)', 'lhu $a0, %lo(entries+0x2)($a0)'),
    ]
    spill = 'sw $ra, 0x10($sp)'
    scheduled = rows[:1] + [(' ', spill, spill)] + rows[1:]
    fixed = dict(variants(source, 'f', '', scheduled))['measured_relocated_array_scale']
    assert 'extern u8 entries[];' in fixed
    assert 'consume(*(u16 *)(entries + (select(3)) * 12));' in fixed
    assert not variants(source, 'f', '', rows[:-1] + [('i', rows[-1][1], 'lhu $a0, %lo(entries+4)($a0)')])


def test_halfword_table_can_have_an_odd_stride_with_a_one_bit_shift():
    source = 'extern M2C_UNK entries;\nu16 f(void) { return *(&entries + (select(3) * 6)); }'
    rows = [
        ('i', 'sll $v0, $v0, 1', 'sll $v0, $v0, 3'),
        ('i', 'lui $at, %hi(entries)', 'lui $at, %hi(entries+2)'),
        (' ', 'addu $at, $at, $v0', 'addu $at, $at, $v0'),
        ('i', 'lhu $v0, %lo(entries)($at)', 'lhu $v0, %lo(entries+2)($at)'),
    ]
    assert 'return *(u16 *)(entries + (select(3)) * 6);' in dict(
        variants(source, 'f', '', rows))['measured_relocated_array_scale']
    assert 'return entries[select(3)];' in dict(
        variants(source.replace('* 6', '* 2'), 'f', '', rows))['measured_relocated_array_scale']


def test_independent_halfword_and_word_table_accesses_are_repaired_in_turn():
    source = ('extern M2C_UNK ids;\nextern M2C_UNK slots;\n'
              'void f(s32 i) { consume(*(&ids + (choose() * 2)), *(&slots + (i * 4))); }')
    halfword = [
        ('i', 'sll $v0, $v0, 1', 'sll $v0, $v0, 3'),
        ('i', 'lui $a0, %hi(ids)', 'lui $a0, %hi(ids+0x2)'),
        (' ', 'addu $a0, $a0, $v0', 'addu $a0, $a0, $v0'),
        ('i', 'lhu $a0, %lo(ids)($a0)', 'lhu $a0, %lo(ids+0x2)($a0)'),
    ]
    word = ['lui $at, %hi(slots)', 'addu $at, $at, $a0', 'lw $v0, %lo(slots)($at)']
    word_rows = SHIFT + [(' ', op, op) for op in word]
    forward = [('r', 'addiu $a1, $sp, 0x10', 'addiu $a0, $sp, 0x10')]
    fixed = dict(variants(source, 'f', '', forward + halfword + word_rows))['measured_relocated_array_scale']
    assert 'consume(ids[choose()], *(&slots + (i * 4)));' in fixed
    fixed = dict(variants(fixed, 'f', '', forward + word_rows))['measured_duplicate_word_scale']
    assert 'consume(ids[choose()], slots[i]);' in fixed


def test_float_field_recovery_preserves_record_stride_and_nested_index():
    source = ('extern M2C_UNK records;\nf32 f(s32 i) {\n'
              '    return *(&records + (fetch(i) * 24)) * 2.0f;\n}')
    rows = [('i', 'sll $v0, $v0, 3', 'sll $v0, $v0, 5')]
    rows += [(' ', op, op) for op in ('lui $at, %hi(records)', 'addu $at, $at, $v0',
                                      'lwc1 $f0, %lo(records)($at)')]
    rows += [('>', '', 'cvt.s.w $f0, $f0')]
    fixed = dict(variants(source, 'f', '', rows))['measured_float_record_scale']
    assert 'extern u8 records[];' in fixed
    assert '*(f32 *)(records + (fetch(i)) * 24) * 2.0f' in fixed
    assert not variants(source, 'f', '', rows[:-1])
    assert not variants(source, 'f', '', rows[:-1] + [('>', '', 'cvt.s.w $f2, $f0')])


def test_guarded_word_reads_correct_a_single_shared_record_stride():
    source = ('extern M2C_UNK first;\nextern M2C_UNK second;\nvoid f(s32 i) {\n'
              '    s32 offset;\n    offset = i * 16;\n'
              '    if (*(&first + offset)) consume(*(&second + offset));\n}')
    rows = [('i', 'sll $a0, $a0, 4', 'sll $a0, $a0, 6')]
    rows += [(' ', op, op) for op in ('lui $at, %hi(first)', 'addu $at, $at, $a0',
                                      'lw $v0, %lo(first)($at)')]
    assert 'offset = i * 4;' in dict(variants(source, 'f', '', rows))['measured_word_stride']
    assert not variants(source.replace('i * 16', 'i * 8'), 'f', '', rows)
    assert not variants(source, 'f', '', rows[:-1])


def test_indirect_halfword_lookup_retypes_the_cursor_and_preserves_other_tables():
    source = '''extern M2C_UNK red;
extern M2C_UNK blue;
s32 f(s32 choice) {
    M2C_UNK *table;
    if (choice) { table = &red; } else { table = &blue; }
    return consume(*((fetch() * 2) + table));
}
'''
    rows = [('i', 'sll $v0, $v0, 1', 'sll $v0, $v0, 3'),
            (' ', 'addu $v0, $v0, $s1', 'addu $v0, $v0, $s1'),
            ('i', 'lhu $a0, ($v0)', 'lhu $a0, 2($v0)')]
    fixed = dict(variants(source, 'f', '', rows))['measured_indirect_halfword_table']
    assert 'u16 *table;' in fixed
    assert 'table = (u16 *)&red;' in fixed and 'table = (u16 *)&blue;' in fixed
    assert 'consume(table[fetch()]);' in fixed
    assert not variants(source.replace('return consume', 'hold(table);\n    return consume'), 'f', '', rows)
    assert not variants(source, 'f', 'extern s32 blue;', rows)


def test_measured_call_uses_byte_stride_for_a_global_record_argument():
    source = 'extern M2C_UNK records;\nvoid f(s32 i) { send(7, (i * 24) + &records, 0); }'
    rows = [('i', 'sll $a1, $a1, 3', 'sll $a1, $a1, 5')]
    rows += [(' ', op, op) for op in ('lui $v0, %hi(records)', 'addiu $v0, $v0, %lo(records)',
                                      'addu $a1, $a1, $v0', 'sw $a3, 16($sp)', 'jal send', 'nop')]
    fixed = dict(variants(source, 'f', '', rows))['measured_scaled_global_call']
    assert 'send(7, (i * 24) + (u8 *)&records, 0)' in fixed
    assert not variants(source, 'f', '', rows[:-1] + [(' ', 'move $a1, $zero', 'move $a1, $zero')])
    assert not variants(source.replace('* 24', '* 12'), 'f', '', rows)


def test_measured_call_scales_offset_after_loading_a_halfword_pointer():
    source = 'extern u16 *values;\ns32 f(void) { return read(values + 2, 7); }'
    rows = [(' ', op, op) for op in ('lui $a0, %hi(values)', 'lw $a0, %lo(values)($a0)',
                                      'lui $a1, %hi(other)', 'lw $a1, %lo(other)($a1)')]
    rows += [('i', 'addiu $a0, $a0, 2', 'addiu $a0, $a0, 4'), (' ', 'jal read', 'jal read')]
    fixed = dict(variants(source, 'f', '', rows))['measured_loaded_halfword_call_offset']
    assert 'read(values + 1, 7)' in fixed
    assert not variants(source.replace('u16 *', 'u8 *'), 'f', '', rows)
    assert not variants(source, 'f', '', rows[1:])


def test_byte_table_recovers_load_width_and_stride_with_matched_byte_store():
    source = ('extern M2C_UNK table;\nvoid f(s32 i, u8 *dst) {\n'
              '    *dst = (u8) *(&table + ((i & 255) * 24));\n}')
    rows = [('o', 'addiu $a0, $zero, 20', ''), ('o', '', 'addiu $a0, $zero, 20'),
            ('i', 'sll $v1, $v1, 3', 'sll $v1, $v1, 5')]
    rows += [(' ', op, op) for op in ('lui $v0, %hi(table)', 'addu $v0, $v0, $v1')]
    rows += [('|', 'lbu $v0, %lo(table)($v0)', 'lw $v0, %lo(table)($v0)'),
             (' ', 'j done', 'j done'), (' ', 'sb $v0, ($a0)', 'sb $v0, ($a0)')]
    fixed = dict(variants(source, 'f', '', rows))['measured_relocated_array_scale']
    assert 'extern u8 table[];' in fixed
    assert '*dst = (u8) table[(i & 255) * 24];' in fixed
    assert not variants(source.replace('(u8) ', ''), 'f', '', rows)
    assert not variants(source, 'f', '', rows[:-1])


def test_shared_word_offset_forms_preloaded_cursor_and_separate_table_reads():
    source = '''extern M2C_UNK first;
extern M2C_UNK second;
void f(void) {
    s32 offset;
    s32 *cursor;
    u16 i;
    for (i = 0; i < 2; i++) {
        offset = i * 4;
        cursor = offset + &first;
        if (*cursor) consume(*(offset + &second));
    }
}
'''
    rows = [(' ', op, op) for op in ('lui $fp, %hi(first)', 'addiu $fp, $fp, %lo(first)',
                                      'andi $v0, $s2, 0xffff')]
    rows += [('i', 'sll $s0, $v0, 2', 'sll $s0, $v0, 4')]
    rows += [(' ', op, op) for op in ('addu $s1, $s0, $fp', 'lw $v0, ($s1)')]
    fixed = dict(variants(source, 'f', '', rows))['measured_preloaded_word_offset']
    assert 'offset = i;' in fixed
    assert not variants(source.replace('if (*cursor)', 'if (offset && *cursor)'), 'f', '', rows)
    assert not variants(source, 'f', '', rows[1:])


def test_call_pointer_scale_uses_a_preloaded_base_and_unchanged_other_argument():
    source = 'extern M2C_UNK blocks;\nvoid f(s32 i) { send((i * 12) + &blocks, 11); }'
    rows = [(' ', op, op) for op in ('lui $s2, %hi(blocks)', 'addiu $s2, $s2, %lo(blocks)',
                                      'addu $a0, $a0, $v0')]
    rows += [('i', 'sll $a0, $a0, 2', 'sll $a0, $a0, 4')]
    rows += [(' ', op, op) for op in ('addu $a0, $a0, $s2', 'jal send', 'addiu $a1, $zero, 11')]
    fixed = dict(variants(source, 'f', '', rows))['measured_scaled_global_call']
    assert 'send((i * 12) + (u8 *)&blocks, 11)' in fixed
    overwrites = (' ', 'addiu $a0, $zero, 11', 'addiu $a0, $zero, 11')
    assert not variants(source, 'f', '', rows[:-1] + [overwrites])


def test_guarded_halfword_read_recovers_stride_from_an_explicit_word_declaration():
    source = 'extern s32 records;\nvoid f(s32 i) { if (*(&records + (i * 24)) == 0) stop(); }'
    rows = [('i', 'sll $v0, $v0, 3', 'sll $v0, $v0, 5')]
    rows += [(' ', op, op) for op in ('lui $at, %hi(records)', 'addu $at, $at, $v0')]
    rows += [('|', 'lhu $v0, %lo(records)($at)', 'lw $v0, %lo(records)($at)'),
             (' ', 'bnez $v0, 32', 'bnez $v0, 32')]
    fixed = dict(variants(source, 'f', '', rows))['measured_guarded_halfword_table']
    assert 'extern u8 records[];' in fixed
    assert 'if (*(u16 *)(records + i * 24) == 0)' in fixed
    assert not variants(source, 'f', '', rows[:-1])
    assert not variants(source, 'f', 'extern s32 records;', rows)


def test_call_record_pointer_is_formed_in_the_delay_slot():
    source = 'extern s32 records;\nvoid f(s32 i) { send(6, (i * 24) + &records); }'
    rows = [(' ', op, op) for op in ('lui $v0, %hi(records)', 'addiu $v0, $v0, %lo(records)')]
    rows += [('i', 'sll $a1, $a1, 3', 'sll $a1, $a1, 5')]
    rows += [(' ', op, op) for op in ('jal send', 'addu $a1, $a1, $v0')]
    fixed = dict(variants(source, 'f', '', rows))['measured_scaled_global_call']
    assert 'send(6, (i * 24) + (u8 *)&records)' in fixed
    assert not variants(source, 'f', '', rows[1:])


def test_paired_halfword_tables_correct_adjacent_loads_and_keep_byte_stride():
    source = '''extern M2C_UNK D_80001000;
extern M2C_UNK D_80001002;
void f(s32 i) {
    s32 offset;
    offset = i * 4;
    send(*(&D_80001000 + offset), *(&D_80001002 + offset));
}
'''
    rows = [(' ', 'sll $v1, $s1, 4', 'sll $v1, $s1, 4')]
    for reg, target, current in (('$a0', 'D_80001000', 'D_80001002'), ('$a1', 'D_80001002', 'D_80001004')):
        add = f'addu {reg}, {reg}, $v1'
        rows.extend([('i', f'lui {reg}, %hi({target})', f'lui {reg}, %hi({current})'),
                     (' ', add, add),
                     ('i', f'lh {reg}, %lo({target})({reg})', f'lh {reg}, %lo({current})({reg})')])
    rows.append((' ', 'jal send', 'jal send'))
    fixed = dict(variants(source, 'f', '', rows))['measured_paired_halfword_call_tables']
    assert 'extern s16 D_80001000;' in fixed and 'extern s16 D_80001002;' in fixed
    assert 'offset = i * 8;' in fixed
    assert not variants(source, 'f', '', rows[:-1])
    assert not variants(source.replace('* 4', '* 8'), 'f', '', rows)
    assert not variants(source, 'f', 'extern u16 D_80001002;', rows)


def test_reordered_call_setup_moves_two_unreferenced_zero_initializations():
    source = '''void f(void *p) {
    s32 left;
    s16 right;
    if (p) {
        left = 0;
        right = 0;
        start(p, 32, 66, 114);
        sink(M2C_FIELD(p, s32 *, 0), left, right);
    }
}'''
    first, second = 'move $s2, $zero', 'move $s4, $zero'
    rows = [('o', '', first), ('o', '', second)]
    rows += [(' ', op, op) for op in ('addiu $a1, $zero, 0x20', 'addiu $a2, $zero, 0x42',
                                      'addiu $a3, $zero, 0x72')]
    rows += [('o', first, ''), ('o', second, ''), (' ', 'jal start', 'jal start'), (' ', 'nop', 'nop')]
    fixed = dict(variants(source, 'f', '', rows))['measured_call_zero_setup']
    assert 'start(p, 32, 66, 114);\n        left = 0;\n        right = 0;' in fixed
    assert not variants(source.replace('start(p', 'start(left'), 'f', '', rows)
    assert not variants(source.replace(', 66,', ', 6,'), 'f', '', rows)


def test_reordered_byte_load_and_dependent_index_follow_the_call():
    source = '''void f(void *p) {
    s32 value;
    s32 index;
    void *object;
    if (p != NULL) {
        value = M2C_FIELD(p, u8 *, 8);
        index = value * 8;
        object = create(4, 0, 2);
        sink(object, index);
    }
}'''
    load = 'lbu $s1, 8($s6)'
    rows = [('o', '', load), (' ', 'jal create', 'jal create'),
            (' ', 'addiu $a2, $zero, 2', 'addiu $a2, $zero, 2'), ('o', load, '')]
    fixed = dict(variants(source, 'f', '', rows))['measured_call_byte_load_setup']
    assert 'object = create(4, 0, 2);\n        value = M2C_FIELD' in fixed
    assert not variants(source.replace('create(4', 'create(index'), 'f', '', rows)
    assert not variants(source.replace('u8 *, 8', 'u8 *, 9'), 'f', '', rows)


def test_loop_step_scales_a_cursor_to_indirect_zeroed_records():
    source = '''extern void *entries;
void f(void) {
    void **cursor;
    s32 i = 0;
    cursor = &entries;
    do {
        M2C_FIELD(*cursor, s32 *, 4) = 0;
        i += 1;
        M2C_FIELD(*cursor, s32 *, 8) = 0;
        cursor += 4;
    } while (i < 3);
}'''
    rows = [(' ', op, op) for op in ('lw $v0, ($v1)', 'sw $zero, 4($v0)', 'lw $v0, ($v1)',
                                      'addiu $a0, $a0, 1', 'sw $zero, 8($v0)', 'sltiu $v0, $a0, 3',
                                      'bnez $v0, 0')]
    rows += [('i', 'addiu $v1, $v1, 4', 'addiu $v1, $v1, 16')]
    fixed = dict(variants(source, 'f', '', rows))['measured_pointer_step']
    assert 'cursor += 1;' in fixed
    assert not variants(source.replace('*, 8', '*, 12'), 'f', '', rows)
    assert not variants(source.replace('void **cursor', 'void *cursor'), 'f', '', rows)


def test_call_stride_uses_argument_register_as_relocated_base():
    source = 'extern s32 records;\ns32 f(s32 i) { return send((i * 104) + &records, 1); }'
    rows = [('i', 'sll $v0, $v0, 3', 'sll $v0, $v0, 5')]
    rows += [(' ', op, op) for op in ('lui $a0, %hi(records)', 'addiu $a0, $a0, %lo(records)',
                                      'addu $a0, $v0, $a0', 'sw $ra, 16($sp)', 'jal send',
                                      'addiu $a1, $zero, 1')]
    fixed = dict(variants(source, 'f', '', rows))['measured_scaled_global_call']
    assert 'send((i * 104) + (u8 *)&records, 1)' in fixed
    assert not variants(source, 'f', '', rows[:-1])
    assert not variants(source.replace('* 104', '* 100'), 'f', '', rows)
