from decomprepair.measured_kmc_cursor_switch import variants


def measured(text):
    return [(' ', op, op) for op in text.splitlines() if op]


def test_buffer_swap_uses_a_local_base_and_a_one_argument_call():
    rows = measured('''
addiu $sp, $sp, -24
sw $ra, 16($sp)
lw $v1, 12($a0)
beqz $v1, 32
move $a1, $a0
lw $v0, 8($a0)
sw $v1, 8($a0)
sw $v0, 12($a0)
jal send
lw $a0, 8($a1)
lw $ra, 16($sp)
jr $ra
addiu $sp, $sp, 24
''')
    rows.insert(1, ('o', '', 'move $a1, $a0'))
    for i in (3, 4, 5, 6, 7, 8):
        rows[i] = ('r', rows[i][1], 'different register')
    source = '''
void send(s32, void *);
void f(void *entry) {
    s32 saved;
    s32 next;
    next = M2C_FIELD(entry, s32 *, 12);
    if (next != 0) {
        saved = M2C_FIELD(entry, s32 *, 8);
        M2C_FIELD(entry, s32 *, 8) = next;
        M2C_FIELD(entry, s32 *, 12) = saved;
    }
    send(M2C_FIELD(entry, s32 *, 8), entry);
}
'''
    [(family, fixed)] = variants(source, 'f', '', rows)
    assert family == 'measured_swap_then_field_call'
    assert 'void *__repair_swap_base = entry;' in fixed
    assert 'send(M2C_FIELD(__repair_swap_base, s32 *, 8));' in fixed
    assert not variants(source, 'f', 'void send(s32, void *);', rows)
    assert not variants(source.replace('12) = saved', '16) = saved'), 'f', '', rows)


def test_byte_cursor_advances_in_the_call_slot_and_preserves_both_stores():
    rows = measured('''
addiu $sp, $sp, -32
sw $s1, 20($sp)
move $s1, $a0
sw $s0, 16($sp)
move $s0, $a1
sw $ra, 24($sp)
lbu $a0, ($s0)
jal read_count
addiu $s0, $s0, 1
move $v1, $v0
sb $v1, 20($s1)
lbu $a0, ($s0)
addiu $v0, $s0, 1
addu $v1, $v1, $a0
sb $v1, 20($s1)
lw $ra, 24($sp)
lw $s1, 20($sp)
lw $s0, 16($sp)
jr $ra
addiu $sp, $sp, 32
''')
    rows.insert(6, ('o', '', 'jal read_count'))
    for i in (8, 9, 12, 13):
        rows[i] = ('r', rows[i][1], '')
    source = '''
s8 read_count(u8);
void *f(void *dst, void *src) {
    s8 value;
    value = read_count(M2C_FIELD(src, u8 *, 0));
    M2C_FIELD(dst, s8 *, 20) = value;
    M2C_FIELD(dst, s8 *, 20) = (s8) (value + M2C_FIELD(src, u8 *, 1));
    return src + 1 + 1;
}
'''
    [(family, fixed)] = variants(source, 'f', '', rows)
    assert family == 'measured_two_byte_call_cursor'
    assert 'int read_count(int);' in fixed and 'u8 *src)' in fixed
    assert 'read_count(*src++);' in fixed and 'value += *src;' in fixed
    assert fixed.count('M2C_FIELD(dst, s8 *, 20) = value;') == 2
    assert not variants(source, 'f', 'void *f(void *dst, void *src);', rows)
    assert not variants(source.replace('return src + 1 + 1;', 'return src + 1;'), 'f', '', rows)


def test_switch_keeps_mask_initializer_separate_from_the_shift():
    rows = measured('''
addiu $v1, $zero, 1
addiu $v0, $zero, 1
beq $a2, $v0, 68
sllv $v1, $v1, $a1
slti $v0, $a2, 2
beql $v0, $zero, 44
addiu $v0, $zero, 2
beql $a2, $zero, 60
nor $v0, $zero, $v1
j f+72
nop
beql $a2, $v0, 72
xor $a0, $a0, $v1
j f+72
nop
j f+72
and $a0, $a0, $v0
or $a0, $a0, $v1
jr $ra
move $v0, $a0
''')
    for i in (0, 2, 3, 5, 7, 9, 11, 13, 15):
        original = '' if i == 0 else 'sllv $v1, $v0, $a1' if i == 3 else 'shifted branch'
        rows[i] = ('r', rows[i][1], original)
    source = '''
s32 f(s32 old, s32 bit, s32 action) {
    s32 mask;
    s32 value;
    value = old;
    mask = 1 << bit;
    switch (action) {
    case 0: value &= ~mask; break;
    case 2: value ^= mask; break;
    case 1: value |= mask; break;
    }
    return value;
}
'''
    [(family, fixed)] = variants(source, 'f', '', rows)
    assert family == 'measured_switch_mask_initializer'
    assert 'mask = 1;\n    value = old;\n    mask = mask << bit;' in fixed
    assert not variants(source.replace('value ^= mask', 'value += mask'), 'f', '', rows)


def test_guarded_tail_drops_only_an_inferred_argument():
    rows = measured('nop\n' * 12 + '''
lui $v0, %hi(ready)
lbu $v0, %lo(ready)($v0)
bnez $v0, 108
addiu $a0, $zero, 1
jal start
addiu $a1, $s0, 32
addiu $a0, $s0, 48
jal load
move $s0, $v0
lui $a1, %hi(table)
addiu $a1, $a1, %lo(table)
jal finish
move $a0, $s0
j f+116
nop
jal notify
nop
lw $ra, 20($sp)
lw $s0, 16($sp)
jr $ra
addiu $sp, $sp, 24
''')
    rows[28] = ('|', 'nop', 'addiu $a0, $zero, 1')
    source = '''
M2C_UNK notify(M2C_UNK);
void f(s32 input) {
    s32 result;
    if (ready == 0) {
        result = start(1, input + 32);
        load(input + 48);
        finish(result, &table);
        return;
    }
    notify(1);
}
'''
    [(family, fixed)] = variants(source, 'f', '', rows)
    assert family == 'measured_guarded_no_argument_call'
    assert 'notify(void);' in fixed and '} else {\n        notify();' in fixed
    assert not variants(source, 'f', 'void notify(s32);', rows)
    assert not variants(source.replace('finish(result', 'finish(input'), 'f', '', rows)


def test_early_exit_uses_argument_register_already_written_by_the_guard():
    rows = measured('''
beqz $v0, 64
addiu $a0, $zero, 6
lui $v0, %hi(table)
lw $v0, %lo(table)($v0)
lhu $v1, 12($v0)
addiu $v0, $zero, 8
beq $v1, $v0, 64
addiu $a0, $zero, 6
jal reset
nop
j f+156
nop
''')
    rows[9] = ('|', 'nop', 'addiu $a0, $zero, 6')
    rows += [(' ', '', '')] * 30
    source = '''
void reset(s32);
void f(void) {
    s32 a;
    void *item;
    if (((flag1 != 0) || (flag2 != 0) || (flag3 != 0)) && (M2C_FIELD(M2C_FIELD(&state, void **, 16), u16 *, 12) != 8)) {
        reset(6);
        return;
    }
    a = prepare();
    finish(a);
}
'''
    [(label, fixed)] = variants(source, 'f', '', rows)
    assert label == 'measured_guard_exit_without_inferred_argument'
    assert 'void reset(void);' in fixed and 'reset();' in fixed
    assert '    a = prepare();' in fixed
    assert not variants(source, 'f', 'void reset(s32);', rows)
    assert not variants(source.replace('!= 8', '!= 9'), 'f', '', rows)


def test_label_loop_cursor_splits_before_a_matching_reinitialization():
    source = """void f(void *base) {
    void *cursor;
    cursor = base;
    first_loop:
    write_halfword(cursor);
    cursor += 2;
    if (more()) goto first_loop;

    cursor = base;
    next_loop:
    write_word(cursor);
    cursor += 4;
    if (more()) goto next_loop;
}
"""
    rows = [
        ('r', 'move $v1, $s5', 'move $s1, $s5'),
        ('r', 'sh $zero, 0x1bc($v1)', 'sh $zero, 0x1bc($s1)'),
        ('r', 'sh $v0, 0x1bc($v1)', 'sh $v0, 0x1bc($s1)'),
        ('r', 'addiu $v1, $v1, 2', 'addiu $s1, $s1, 2'),
    ]
    [(family, fixed)] = variants(source, 'f', '', rows)
    assert family == 'measured_label_loop_cursor'
    assert 'void *__repair_first_loop_cursor;' in fixed
    assert 'write_halfword(__repair_first_loop_cursor);' in fixed
    assert 'write_word(cursor);' in fixed
    assert not variants(source.replace('cursor += 2;', 'cursor += 8;'), 'f', '', rows)
    assert not variants(source.replace('if (more()) goto first_loop;', 'if (more()) goto first_loop;\n    use(cursor);'),
                        'f', '', rows)
    assert not variants(source.replace('write_halfword(cursor)', 'write_halfword(&cursor)'), 'f', '', rows)
    assert not variants(source.replace('    cursor = base;\n    next_loop:', '    next_loop:'), 'f', '', rows)
