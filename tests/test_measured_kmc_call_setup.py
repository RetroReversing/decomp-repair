from decomprepair.measured_kmc_call_setup import variants


def diff(asm, replacements, extra=(), length=34):
    rows = [('r' if line in replacements else ' ', line, replacements.get(line, line))
            for line in asm.strip().splitlines()]
    rows += [('>', '', line) for line in extra]
    return rows + [(' ', '', '')] * max(length - len(rows), 0)


def test_branch_uses_remaining_mask_at_final_call():
    rows = diff('''
move $a0, $s2
jal pause
move $a1, $zero
andi $v0, $s1, 16
beqz $v0, 36
move $a0, $s2
j f+40
addiu $a1, $zero, 1
move $a1, $zero
jal pause
nop
''', {'andi $v0, $s1, 16': ''})
    source = '''
void f(s32 ctx, s32 value) {
    s32 state;
    s32 flag;
    flag = value & 16;
    if (value & 8) {
        refresh(ctx);
        pause(ctx, 0);
        flag = value & 16;
    }
    if (flag != 0) {
        state = 1;
        pause(ctx, state);
    } else {
        state = 0;
        pause(ctx, state);
    }
}
'''
    [(label, fixed)] = variants(source, 'f', '', rows)
    assert label == 'measured_mask_at_final_call'
    assert 'if (value & 16)' in fixed
    assert 'refresh(ctx);' in fixed
    assert 'pause(ctx, 1);' in fixed and fixed.count('pause(ctx, 0);') == 2
    assert 'flag =' not in fixed
    assert not variants(source.replace('refresh(ctx);', 'refresh(flag);'), 'f', '', rows)


def test_delay_slot_field_is_second_argument_after_context():
    rows = diff('''
addiu $sp, $sp, -24
sw $ra, 16($sp)
lw $v0, 20($a0)
lw $v1, 4($v0)
lw $a3, 8($v0)
subu $v1, $v1, $a3
mult $a1, $v1
mflo $v1
lui $v0, 20971
ori $v0, $v0, 34079
lw $v0, 20($a0)
jal send
lw $a1, 32($v0)
lw $ra, 16($sp)
jr $ra
addiu $sp, $sp, 24
''', {'lw $a1, 32($v0)': 'lw $a0, 32($v0)'}, ('move $a3, $a1',))
    source = '''
void send(s32, void *, s32);
void f(void *ctx, s32 amount) {
    s32 value;
    void *base;
    void *obj;
    base = M2C_FIELD(ctx, void **, 20);
    value = M2C_FIELD(base, s32 *, 8);
    obj = M2C_FIELD(ctx, void **, 36);
    M2C_FIELD(obj, s32 *, 4) = (s32) (((amount * (M2C_FIELD(base, s32 *, 4) - value)) / 100) + value);
    send(M2C_FIELD(M2C_FIELD(ctx, void **, 20), s32 *, 32), obj, value);
}
'''
    [(label, fixed)] = variants(source, 'f', '', rows)
    assert label == 'measured_keep_first_call_argument'
    assert 'send(void *, s32);' in fixed
    assert 'send(ctx, M2C_FIELD(' in fixed
    assert fixed.index('__repair_first_value =') < fixed.index('value = M2C_FIELD(base, s32 *, 8)')
    assert not variants(source, 'f', 'void send(s32, void *, s32);', rows)


def test_global_pointer_is_captured_before_halfword_update():
    rows = diff('''
lw $v1, ($s1)
lhu $v0, 6($v1)
lui $a0, %hi(global)
lw $a0, %lo(global)($a0)
move $s0, $zero
addiu $v0, $v0, -12
sh $v0, 6($v1)
lw $a2, 8($a0)
addiu $a1, $zero, 1
jal send
addiu $a0, $zero, 3
''', {'sh $v0, 6($v1)': ''}, ('sh $v0, 6($v1)',))
    source = '''
extern void *global;
void f(void *item) {
    void *base;
    s32 result;
    base = M2C_FIELD(item, void **, 0);
    result = 0;
    M2C_FIELD(base, u16 *, 6) = (u16) (M2C_FIELD(base, u16 *, 6) - 12);
    send(3, 1, M2C_FIELD(global, s32 *, 8));
}
'''
    [(label, fixed)] = variants(source, 'f', '', rows)
    assert label == 'measured_global_pointer_before_update'
    assert fixed.index('__repair_global_base = global;') < fixed.index('result = 0;')
    assert 'send(3, 1, M2C_FIELD(__repair_global_base, s32 *, 8));' in fixed
    assert not variants(source.replace('- 12', '- 13'), 'f', '', rows)


def test_stack_record_retains_payload_and_frame_tail():
    rows = diff('''
addiu $sp, $sp, -56
addiu $a0, $s4, 32
addiu $a1, $sp, 16
move $a2, $s5
addiu $v0, $zero, 4
sh $v0, 16($sp)
jal post
sw $s3, 20($sp)
''', {'addiu $sp, $sp, -56': 'addiu $sp, $sp, -48', 'sw $s3, 20($sp)': ''})
    source = '''
void f(void *queue, void *input, s32 delay) {
    s16 sp10;
    void *sp14;
    prepare(input, delay);
    sp10 = 4;
    sp14 = input;
    post(queue + 32, &sp10, delay);
}
'''
    [(label, fixed)] = variants(source, 'f', '', rows)
    assert label == 'measured_delayed_stack_record_payload'
    assert 's32 event_tail[2];' in fixed
    assert '__repair_event.event_payload = input;' in fixed
    assert 'post(queue + 32, (s16 *) &__repair_event, delay);' in fixed
    assert not variants(source, 'f', '#define event_tag something', rows)
    assert not variants(source.replace('void *sp14', 'void *sp18').replace('sp14 =', 'sp18 ='), 'f', '', rows)
