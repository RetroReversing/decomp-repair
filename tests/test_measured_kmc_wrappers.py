from decomprepair.measured_kmc_wrappers import variants


def test_preserve_copy_destination_in_return_register():
    ops = (
        'lw $v1, ($a1)', 'move $v0, $a0', 'sw $v1, 16($v0)', 'lw $v1, 4($a1)',
        'sw $v1, 20($v0)', 'lw $v1, 8($a1)', 'jr $ra', 'sw $v1, 24($v0)',
    )
    rows = [(' ', op, op) for op in ops]
    rows[1] = ('<', ops[1], '')
    source = '''
void copy(void *dst, void *src) {
    M2C_FIELD(dst, s32 *, 16) = M2C_FIELD(src, s32 *, 0);
    M2C_FIELD(dst, s32 *, 20) = (s32) M2C_FIELD(src, s32 *, 4);
    M2C_FIELD(dst, s32 *, 24) = M2C_FIELD(src, s32 *, 8);
}
'''
    [(family, fixed)] = variants(source, 'copy', '', rows)
    assert family == 'measured_return_copy_destination'
    assert 'void *copy' in fixed and 'return dst;' in fixed
    assert not variants(source, 'copy', 'void copy(void *, void *);', rows)
    assert not variants(source.replace('24)', '28)'), 'copy', '', rows)


def test_restore_unsigned_boolean_before_negating_the_mask():
    ops = (
        'addiu $sp, $sp, -24', 'sw $ra, 16($sp)', 'jal lookup', 'nop',
        'sltu $v1, $zero, $v0', 'negu $v1, $v1', 'lw $ra, 16($sp)',
        'and $v0, $v0, $v1', 'jr $ra', 'addiu $sp, $sp, 24',
    )
    rows = [(' ', op, op) for op in ops]
    rows[4] = ('<', ops[4], '')
    source = '''
s32 lookup(void);
s32 f(void) {
    s32 value;
    value = lookup();
    return value & -(value);
}
'''
    [(family, fixed)] = variants(source, 'f', '', rows)
    assert family == 'measured_unsigned_nonzero_mask'
    assert 'return value & -((u32)value > 0);' in fixed
    assert not variants(source.replace('value = lookup()', 'value = other()'), 'f', '', rows)
    rows[4] = ('r', ops[4], 'slt $v1, $zero, $v0')
    assert not variants(source, 'f', '', rows)


def test_ignored_callee_return_type_when_wrapper_returns_zero():
    ops = (
        'addiu $sp, $sp, -24', 'sw $ra, 16($sp)', 'jal refresh', 'move $a0, $zero',
        'lui $v0, %hi(ctx)', 'lw $v0, %lo(ctx)($v0)', 'sb $zero, 4($v0)',
        'lw $ra, 16($sp)', 'move $v0, $zero', 'jr $ra', 'addiu $sp, $sp, 24',
    )
    rows = [(' ', op, op) for op in ops]
    rows[4] = ('r', ops[4], 'lui $v1, %hi(ctx)')
    source = '''
M2C_UNK refresh(s32);
extern void *ctx;
s32 f(void) {
    refresh(0);
    M2C_FIELD(ctx, u8 *, 4) = 0;
    return 0;
}
'''
    [(family, fixed)] = variants(source, 'f', '', rows)
    assert family == 'measured_void_wrapper_callees'
    assert 'void refresh(s32);' in fixed
    assert not variants(source, 'f', 's32 refresh(s32);', rows)
    assert not variants(source.replace('return 0;', 'return refresh(0);'), 'f', '', rows)
    assert not variants(source + '\nvoid other(void) { refresh(0); }\n', 'f', '', rows)


def test_uncached_word_write_and_shared_status():
    ops = (
        'lui $v0, 0xa012', 'ori $v0, $v0, 0x1234', 'lw $v0, ($v0)', 'andi $v0, $v0, 2',
        'beqz $v0, 0x24', 'lui $v0, %hi(D_A0121340)', 'sw $a0, %lo(D_A0121340)($v0)',
        'j f+0x28', 'move $v0, $zero', 'addiu $v0, $zero, -1', 'jr $ra', 'nop',
    )
    rows = [(' ', op, op) for op in ops]
    rows[5] = ('r', ops[5], 'lui $at, %hi(D_A0121340)')
    source = '''
extern s32 D_A0121340;
s32 f(s32 value) {
    if (*(volatile s32 *)0xA0121234 & 2) { goto write; }
    return -1;
    write: {
        D_A0121340 = value;
        return 0;
    }
}
'''
    [(family, fixed)] = variants(source, 'f', '', rows)
    assert family == 'measured_mmio_write_status'
    assert '*(volatile s32 *)0xA0121340 = value;' in fixed
    assert 'return __repair_mmio_status;' in fixed
    assert not variants(source.replace('0xA0121234', '0xA0121238'), 'f', '', rows)
    assert not variants(source.replace('return -1;', 'return -2;'), 'f', '', rows)
