from decomprepair.measured_kmc_flow import variants


def measured(ops):
    return [(' ', op, op) for op in ops]


def test_halfword_limit_crosses_two_coordinate_stores():
    before = ('addiu $a2, $zero, 511', 'sh $a2, 4($a0)')
    rows = [('o', '', op) for op in before]
    rows += measured(('lh $v0, 8($a1)', 'sll $v0, $v0, 1', 'sh $v0, ($a0)', 'lh $v0, 10($a1)'))
    rows.extend(('o', op, '') for op in before)
    rows += measured(('sh $zero, 6($a0)', 'sll $v0, $v0, 1', 'sh $v0, 2($a0)', *('nop',) * 13))
    source = '''
void f(void *out, void *in) {
    M2C_FIELD(out, s16 *, 4) = 511;
    M2C_FIELD(out, s16 *, 0) = (s16) (M2C_FIELD(in, s16 *, 8) * 2);
    M2C_FIELD(out, s16 *, 2) = (s16) (M2C_FIELD(in, s16 *, 10) * 2);
    M2C_FIELD(out, s16 *, 6) = 0;
}
'''
    [(family, fixed)] = variants(source, 'f', '', rows)
    assert family == 'measured_late_halfword_limit'
    assert fixed.index('M2C_FIELD(out, s16 *, 2)') < fixed.index('= 511;') < fixed.index('= 0;')
    assert not variants(source.replace('10) * 2', '12) * 2'), 'f', '', rows)


def test_moved_relocated_store_selects_existing_forward_branch_repair():
    move = ('lui $at, %hi(slot)', 'sw $v0, %lo(slot)($at)')
    rows = measured([*('nop',) * 12, 'jal fill', 'addiu $a2, $zero, 3'])
    rows.extend(('o', '', op) for op in move)
    rows += measured(('move $a0, $s0', 'addiu $a1, $zero, 1'))
    rows.extend(('o', op, '') for op in move)
    rows += measured(('jal fill', 'addiu $a2, $zero, 3', 'nop'))
    source = '''
void f(s32 flags) {
    s32 value;
    if (flags & 1) {
        value = fill(flags, 1, 3);
        slot = value;
        goto tail;
    }
    if (flags & 2) {
        slot = fill(flags, 1, 3);
        value = fill(flags, 1, 3);
tail:
        use(value);
    }
}
'''
    [(family, fixed)] = variants(source, 'f', '', rows)
    assert family == 'measured_split_store_tail'
    assert fixed.count('use(value);') == 2
    assert 'goto tail;' not in fixed
    assert not variants(source, 'f', '', rows[:-3] + [(' ', 'nop', 'nop')] * 3)
    assert not variants(source, 'f', '', rows[:-3] + [('o', 'nop', '')] * 3)


def test_stages_double_products_and_single_precision_call_result():
    rows = measured((
        'lui $at, %hi(coarse)', 'ldc1 $f2, %lo(coarse)($at)', 'mtc1 $a0, $f0', 'nop',
        'cvt.d.w $f0, $f0', 'mul.d $f0, $f0, $f2', 'lui $at, %hi(fine)', 'ldc1 $f2, %lo(fine)($at)',
        'cvt.s.d $f12, $f0', 'cvt.d.s $f12, $f12', 'mul.d $f12, $f12, $f2', 'addiu $sp, $sp, -24',
        'sw $ra, 16($sp)', 'jal transform', 'cvt.s.d $f12, $f12', 'lui $at, 0x4580',
        'mtc1 $at, $f2', 'nop', 'mul.s $f12, $f0, $f2', 'trunc.w.s $f0, $f12', 'mfc1 $v0, $f0',
        'nop', 'lw $ra, 16($sp)', 'jr $ra', 'addiu $sp, $sp, 24',
    ))
    for index, previous in (
        (8, 'cvt.s.d $f0, $f0'), (9, 'cvt.d.s $f12, $f0'), (18, 'mul.s $f0, $f0, $f2'),
        (19, 'trunc.w.s $f2, $f0'), (20, 'mfc1 $v0, $f2'), (21, ''),
    ):
        rows[index] = ('r', rows[index][1], previous)
    source = '''
s32 f(s32 angle) {
    return (s32) (transform((f32) ((f64) (f32) ((f64) angle * coarse) * fine)) * 4096.0f);
}
'''
    [(family, fixed)] = variants(source, 'f', '', rows)
    assert family == 'measured_staged_float_conversion'
    assert '__repair_float_stage *= 4096.0f;' in fixed
    assert '\n    return (s32)__repair_float_stage;' in fixed
    assert not variants(source.replace('4096.0f', '128.0f'), 'f', '', rows)
    assert not variants(source.replace('* fine', '* other'), 'f', '', rows)


def test_capture_call_result_before_building_the_destination():
    rows = measured((
        *('nop',) * 15, 'lw $v0, 40($s2)', 'addiu $a0, $s1, 52', 'lw $s0, ($v0)', 'jal acquire',
        'move $a1, $zero', 'addu $s0, $s3, $s0', 'lw $v1, 16($s0)', 'sw $v0, 12($s0)',
    ))
    rows.insert(16, ('o', '', 'lw $s0, ($v0)'))
    rows[18] = ('o', 'lw $s0, ($v0)', 'move $a1, $zero')
    rows[20] = ('o', 'move $a1, $zero', '')
    source = '''
void f(void *owner, void *node, s32 index) {
    s32 base;
    void *entry;
    base = *M2C_FIELD(node, s32 **, 40);
    entry = ((index & 0xFF) * 4) + base;
    M2C_FIELD(entry, s32 *, 12) = acquire(owner + 52, 0);
}
'''
    [(family, fixed)] = variants(source, 'f', '', rows)
    assert family == 'measured_staged_call_result'
    assert 's32 __repair_call_result;' in fixed
    assert fixed.index('= acquire(owner + 52, 0);') < fixed.index('entry =')
    assert 'M2C_FIELD(entry, s32 *, 12) = __repair_call_result;' in fixed
    assert not variants(source.replace('owner + 52', 'owner + 56'), 'f', '', rows)


def test_indirect_call_precedes_private_counter_update():
    rows = measured((*('nop',) * 15, 'lw $s0, 40($s2)'))
    rows.extend([
        ('o', '', 'subu $s3, $s3, $s1'),
        (' ', 'addiu $a1, $zero, 3', 'addiu $a1, $zero, 3'),
        ('o', '', 'lw $v0, 8($s0)'),
        (' ', 'move $a2, $s5', 'move $a2, $s5'),
        ('o', 'lw $v0, 8($s0)', ''),
        ('o', 'subu $s3, $s3, $s1', ''),
        (' ', 'jalr $v0', 'jalr $v0'),
        (' ', 'move $a0, $s0', 'move $a0, $s0'),
    ])
    source = '''
void f(void *handle, s32 extra) {
    s32 remaining;
    s32 step;
    remaining = 12;
    step = 4;
    remaining -= step;
    M2C_FIELD(handle, M2C_UNK (**)(void *, M2C_UNK, s32), 8)(handle, 3, extra);
    keep(remaining);
}
'''
    [(family, fixed)] = variants(source, 'f', '', rows)
    assert family == 'measured_post_indirect_call_update'
    assert fixed.index('8)(handle, 3, extra);') < fixed.index('remaining -= step;')
    assert not variants(source.replace('keep(remaining)', 'keep(&remaining)'), 'f', '', rows)


def test_guarded_constant_stores_preserve_comparisons_and_the_shared_field():
    source = """void f(void *obj, u32 key) {
    s16 result;
    if (((s32) key >= 10) && ((result = 50, (((s32) key < 12) != 0)) || (result = 60, (((s32) key < 14) != 0)))) {
        M2C_FIELD(obj, s16 *, 24) = result;
    }
}
"""
    rows = [
        ('r', 'addiu $v0, $zero, 50', 'addiu $a0, $zero, 50'),
        ('r', 'addiu $v0, $zero, 0x3c', 'addiu $a0, $zero, 0x3c'),
        ('r', 'sh $v0, 0x18($a0)', 'sh $a0, 0x18($a1)'),
    ]
    [(family, fixed)] = variants(source, 'f', '', rows)
    assert family == 'guarded_constant_stores'
    assert 'if ((s32) key >= 10)' in fixed
    assert 'if ((s32) key < 12)' in fixed
    assert 'else if ((s32) key < 14)' in fixed
    assert 'M2C_FIELD(obj, s16 *, 24) = 50;' in fixed
    assert 'M2C_FIELD(obj, s16 *, 24) = 60;' in fixed
    assert 'result' not in fixed
    assert not variants(source.replace('24)', '28)'), 'f', '', rows)
    assert not variants(source.replace('s16 result;', 's16 result; use(&result);'), 'f', '', rows)
    assert not variants(source, 'f', '', rows[:2])
