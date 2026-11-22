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


def test_early_float_field_load_follows_the_child_pointer_read():
    source = """void f(void *parent) {
    void *child;
    child = M2C_FIELD(parent, void **, 108);
    M2C_FIELD(child, s16 *, 38) = 1;
    M2C_FIELD(child, f32 *, 28) = (f32) (M2C_FIELD(parent, f32 *, 40) - 1.0f);
}
"""
    read, sub = 'lwc1 $f0, 0x28($s0)', 'sub.s $f0, $f0, $f2'
    rows = measured(['lw $v0, 0x6c($s0)'])
    rows += [('o', read, ''), ('o', sub, '')]
    rows += measured(['sh $v1, 0x26($v0)'])
    rows += [('o', '', read), ('o', '', sub)]
    rows += measured(['swc1 $f0, 0x1c($v0)'])
    [(family, fixed)] = variants(source, 'f', '', rows)
    assert family == 'measured_early_float_field_load'
    assert 'f32 __repair_parent_float;' in fixed
    assert '    __repair_parent_float = M2C_FIELD(parent, f32 *, 40);\n    M2C_FIELD(child, s16' in fixed
    assert '(f32) (__repair_parent_float - 1.0f)' in fixed
    assert not variants(source.replace('*, 40)', '*, 44)'), 'f', '', rows)
    assert not variants(source.replace(' = 1;', ' = input();'), 'f', '', rows)
    assert not variants(source, 'f', '', rows[:-1] + measured(['swc1 $f0, 0x1c($a0)']))


def test_float_scale_carrier_stages_both_loads_without_reassociation():
    source = """extern f32 table[];
f32 f(int key, int plain, f32 factor) {
    f32 scale;
    if (plain) {
        scale = table[key] * factor;
    } else {
        f32 coefficient;
        coefficient = 0.5f;
        coefficient = table[key] * coefficient;
        scale = coefficient * factor;
    }
    return scale;
}
"""
    load = ('r', 'lwc1 $f2, %lo(table)($at)', 'lwc1 $f0, %lo(table)($at)')
    multiply = ('r', 'mul.s $f2, $f2, $f4', 'mul.s $f2, $f0, $f4')
    literal = ('r', 'mtc1 $at, $f0', 'mtc1 $at, $f2')
    rows = [load, multiply, literal, load]
    [(family, fixed)] = variants(source, 'f', '', rows)
    assert family == 'measured_float_scale_carrier'
    assert 'scale = table[key];\n        scale *= factor;' in fixed
    assert 'scale = table[key];\n        scale *= coefficient;\n        scale *= factor;' in fixed
    assert not variants(source, 'f', '', rows[:-1])
    assert not variants(source.replace('coefficient * factor;', 'coefficient * factor;\n        use(coefficient);'),
                        'f', '', rows)


def test_byte_subtraction_reuses_the_signed_result_instead_of_the_pointer():
    source = """void f(void *obj, void *child) {
    short result;
    void *pointer;
    result = *((u8 *) (((char *) child) + 38));
    pointer = (void *) (*((u8 *) (((char *) obj) + 130))); result = (u32) pointer - result;
    if (result < 0) use(result);
}
"""
    rows = [
        ('r', 'lbu $a0, 0x26($s1)', 'lbu $a1, 0x26($s1)'),
        ('r', 'lbu $a1, 0x82($s0)', 'lbu $a2, 0x82($s0)'),
        ('r', 'subu $a0, $a1, $a0', 'subu $v1, $a2, $a1'),
        ('r', 'bgez $a0, 0x18c', 'bgez $v1, 0x18c'),
    ]
    [(family, fixed)] = variants(source, 'f', '', rows)
    assert family == 'measured_byte_subtraction_carrier'
    assert 'result = *((u8 *) (((char *) obj) + 130));' in fixed
    assert 'result -= *((u8 *) (((char *) child) + 38));' in fixed
    assert not variants(source.replace('+ 130', '+ 132'), 'f', '', rows)
    assert not variants(source.replace('use(result)', 'use(pointer)'), 'f', '', rows)
    assert not variants(source, 'f', '', rows[:-1])


def test_interpolated_product_preserves_grouping_and_later_temporary_values():
    source = """extern f32 table[];
f32 f(int i) {
    f32 gain, mix, tmp, out;
    gain = 2.0f;
    mix = 0.25f;
    tmp = ((1.0f-mix)*table[i]+mix*table[i+1]);
    out = gain * tmp;
    if (i != 0) {
        tmp = 1.0f;
        out += tmp;
    }
    return out;
}
"""
    branch = 'bne $a3, $t2, 0x80'
    rows = [
        ('r', 'add.s $f2, $f2, $f0', 'add.s $f0, $f2, $f0'),
        (' ', branch, branch),
        ('r', 'mul.s $f6, $f6, $f2', 'mul.s $f6, $f6, $f0'),
    ]
    [(family, fixed)] = variants(source, 'f', '', rows)
    assert family == 'measured_inline_interpolated_product'
    assert 'out = gain*((1.0f-mix)*table[i]+mix*table[i+1]);' in fixed
    assert 'tmp = 1.0f;' in fixed
    assert not variants(source.replace('return out;', 'return out + tmp;'), 'f', '', rows)
    assert not variants(source.replace('tmp = ((1.0f', 'if (i)\n    tmp = ((1.0f'), 'f', '', rows)
    assert not variants(source, 'f', '', rows[:-1])


def test_identical_branch_assignments_collapse_plain_and_wrapped_arms():
    source = """s32 f(s32 input) {
    f32 score;
    f32 a;
    f32 b;
    s32 ok;
    s32 result;
    score = input;
    a = score + 1.0f;
    b = score - 1.0f;
    if (score) {
        do { ok = 1; } while (0);
    } else {
        ok = 1;
    }
    if (a || b) {
        result = 0;
    } else {
        result = 0;
    }
    return ok + result;
}
"""
    rows = [('>', '', 'move $t1, $zero')]
    fixed = [candidate for family, candidate in variants(source, 'f', '', rows)
             if family == 'measured_identical_branch_assignments']
    assert len(fixed) == 3
    assert 'if (score)' not in fixed[0] and 'if (a || b)' not in fixed[0]
    assert any('if (score)' in candidate for candidate in fixed)
    assert any('if (a || b)' in candidate for candidate in fixed)
    for guarded in (source.replace('f32 score;', 'volatile f32 score;'), source.replace('if (score)', 'if (observe())')):
        [(family, candidate)] = variants(guarded, 'f', '', rows)
        assert family == 'measured_identical_branch_assignments'
        assert 'if (a || b)' not in candidate and 'else {' in candidate
    assert not variants(source, 'f', '', [(' ', 'move $t1, $zero', 'move $t1, $zero')])


def test_byte_guard_return_keeps_the_zero_exit():
    source = """int probe(void *p, int n) {
    if (!p) empty: return 0;
    if (*(unsigned char *)((char *)p + 8) == 0)
        return n <= *(unsigned char *)((char *)p + 4);
    goto empty;
}"""
    rows = [
        ('r', 'lbu $v1, 8($a0)', 'lbu $v0, 8($a0)'),
        ('r', 'bnez $v1, 0x20', 'bnez $v0, 0x20'),
    ]
    [(family, candidate)] = variants(source, 'probe', '', rows)
    assert family == 'measured_byte_guard_return'
    assert 'int __repair_guard_result = *(unsigned char *)((char *)p + 8);' in candidate
    assert 'else goto empty; return __repair_guard_result;' in candidate
    assert not variants(source.replace('empty: return 0;', 'empty: return 1;'), 'probe', '', rows)
    assert not variants(source.replace('p + 8', 'p + 9'), 'probe', '', rows)


def test_in_place_float_ranges_reuses_dead_extrema():
    source = """extern f32 scale;
void probe(void) {
    f32 x; f32 y; f32 x_hi; f32 x_lo; f32 y_hi; f32 y_lo;
    x = x_hi - x_lo;
    y = y_hi - y_lo;
    if (y < x) { do { scale = x; } while (0); }
    else { scale = y; }
    scale *= 0.75f;
}"""
    rows = [
        ('r', 'sub.s $f4, $f4, $f8', 'sub.s $f0, $f4, $f8'),
        ('r', 'c.lt.s $f2, $f4', 'c.lt.s $f2, $f0'),
        ('r', 'swc1 $f4, %lo(scale)($at)', 'swc1 $f0, %lo(scale)($at)'),
    ]
    [(family, candidate)] = variants(source, 'probe', '', rows)
    assert family == 'measured_in_place_float_ranges'
    assert 'x_hi -= x_lo;' in candidate
    assert 'if (y_hi < x_hi) { scale = x_hi; } else { scale = y_hi; }' in candidate
    assert not variants(source.replace('0.75f', 'x_hi'), 'probe', '', rows)
    assert not variants(source.replace('x = x_hi', 'expose(&x_hi); x = x_hi'), 'probe', '', rows)


def test_float_sum_destination_preserves_operand_order_and_scope():
    source = """float probe(f32 n, f32 initial, int enabled) {
    f32 square, total;
    total = initial;
    square = n * n;
    if (enabled)
        total += square;
    return total;
}"""
    rows = [
        ('r', 'mul.s $f12, $f24, $f24', 'mul.s $f2, $f24, $f24'),
        ('r', 'mul.s $f0, $f22, $f22', 'mul.s $f12, $f22, $f22'),
        ('r', 'mul.s $f2, $f20, $f20', 'mul.s $f0, $f20, $f20'),
        ('r', 'add.s $f12, $f12, $f0', 'add.s $f12, $f12, $f2'),
        ('r', 'add.s $f12, $f12, $f2', 'add.s $f12, $f12, $f0'),
    ]
    [(family, candidate)] = variants(source, 'probe', '', rows)
    assert family == 'measured_float_sum_destination'
    assert 'if (enabled)\n        { square = total + square; total = square; }' in candidate
    assert not variants(source.replace('return total;', 'return total + square;'), 'probe', '', rows)
    assert not variants(source, 'probe', '', list(reversed(rows)))


def test_packed_color_channels_requires_the_complete_register_swap():
    source = """void probe(Color *out, u32 input) {
    u32 value = input;
    u32 red, blue, alpha;
    alpha = 0xff000000U;
    red = (value >> 1) << 16;
    blue = (255U - value) | 64U;
    value = red | alpha;
    alpha = 0x7f800000U;
    red >>= 1;
    value |= blue;
    blue >>= 1;
    out->first = value;
    out->second = (blue | alpha) | red;
}"""
    rows = [
        ('r', 'srl $v0, $a0, 1', 'srl $v1, $a0, 1'),
        ('r', 'sll $v0, $v0, 0x10', 'sll $v1, $v1, 0x10'),
        ('r', 'addiu $v1, $zero, 0xff', 'addiu $v0, $zero, 0xff'),
        ('r', 'subu $v1, $v1, $a0', 'subu $v0, $v0, $a0'),
        ('r', 'ori $v1, $v1, 0x40', 'ori $v0, $v0, 0x40'),
        ('r', 'or $a0, $v0, $a1', 'or $a0, $v1, $a1'),
        (' ', 'lui $a1, 0x7f80', 'lui $a1, 0x7f80'),
        ('r', 'srl $v0, $v0, 1', 'srl $v1, $v1, 1'),
        ('r', 'or $a0, $a0, $v1', 'or $a0, $a0, $v0'),
        ('r', 'srl $v1, $v1, 1', 'srl $v0, $v0, 1'),
    ]
    [(family, candidate)] = variants(source, 'probe', '', rows)
    assert family == 'measured_packed_color_channels'
    assert 'do { red = (value >> 1) << 16; } while (0);' in candidate
    assert 'out->second = (red | alpha) | blue;' in candidate
    assert not variants(source.replace('255U', '254U'), 'probe', '', rows)
    assert not variants(source, 'probe', '', rows[:-1])


def test_scaled_field_store_reuses_only_a_dead_unsigned_local():
    source = """void probe(Buffer *out, u32 rate) {
    u32 length;
    length = rate / 160;
    out->length = (length * 5) << 5;
    consume(out->length);
}"""
    rows = measured(('sll $v0, $a0, 2', 'addu $v0, $v0, $a0'))
    rows += [
        ('r', 'sll $a0, $v0, 5', 'sll $v0, $v0, 5'),
        (' ', 'beqz $v1, 0x178', 'beqz $v1, 0x178'),
        ('r', 'sw $a0, 0x1214($s1)', 'sw $v0, 0x1214($s1)'),
    ]
    [(family, candidate)] = variants(source, 'probe', '', rows)
    assert family == 'measured_scaled_field_store'
    assert '{ length = (length * 5) << 5; out->length = length; }' in candidate
    assert not variants(source.replace('consume(out->length)', 'consume(length)'), 'probe', '', rows)
    assert not variants(source, 'probe', '#define length count', rows)
    assert not variants(source, 'probe', '', rows[:-1])


def test_link_pointer_reload_preserves_a_fresh_read():
    source = """void probe(void *node, void *anchor) {
    void *old;
    old = M2C_FIELD(anchor, void **, 0);
    if (old != NULL) {
        M2C_FIELD(old, void **, 4) = node;
    }
    M2C_FIELD(node, void **, 4) = anchor;
    M2C_FIELD(node, void **, 0) = (void *) M2C_FIELD(anchor, void **, 0);
    M2C_FIELD(anchor, void **, 0) = node;
}"""
    rows = measured(('lw $v0, ($a1)', 'bnel $v0, $zero, 0x1c', 'sw $v1, 4($v0)'))
    rows += [('o', '', 'sw $a1, 4($v1)'), (' ', 'lw $v0, ($a1)', 'lw $v0, ($a1)'),
             ('o', 'sw $a1, 4($v1)', '')]
    [(family, candidate)] = variants(source, 'probe', '', rows)
    assert family == 'measured_link_pointer_reload'
    assert candidate.count('old = M2C_FIELD(anchor, void **, 0);') == 2
    assert 'M2C_FIELD(node, void **, 0) = old;' in candidate
    assert not variants(source.replace('M2C_FIELD(old,', 'M2C_FIELD(anchor,'), 'probe', '', rows)
    assert not variants(source, 'probe', '', rows[:-1])


def test_record_float_reset_requires_the_disjoint_reset_sequence():
    source = """void probe(void *p) {
    s32 saved;
    saved = M2C_FIELD(p, s32 *, 0);
    M2C_FIELD(p, s8 *, 0x18) = 0;
    M2C_FIELD(p, u8 *, 0x19) = 0U;
    M2C_FIELD(p, s8 *, 0x1c) = 0;
    M2C_FIELD(p, s8 *, 0x1d) = 0;
    M2C_FIELD(p, s16 *, 0x14) = 0;
    M2C_FIELD(p, s32 *, 0x10) = 0;
    M2C_FIELD(p, f32 *, 0xc) = 1.0f;
}"""
    load = 'lw $a0, ($s0)'
    rows = [('o', '', load)] + measured(('lui $at, 0x3f80', 'mtc1 $at, $f0'))
    rows += [('o', load, '')] + measured((
        'sb $zero, 0x18($s0)', 'sb $zero, 0x19($s0)', 'sb $zero, 0x1c($s0)',
        'sb $zero, 0x1d($s0)', 'sh $zero, 0x14($s0)', 'sw $zero, 0x10($s0)',
    ))
    [(family, candidate)] = variants(source, 'probe', '', rows)
    assert family == 'measured_record_float_reset'
    assert candidate.index('= 1.0f;') < candidate.index('saved =')
    assert not variants(source.replace('f32 *, 0xc', 'f32 *, 0'), 'probe', '', rows)
    assert not variants(source, 'probe', '', rows[:-1])


def test_volatile_table_base_stages_only_the_matching_load():
    source = """extern Entry *volatile table;
void probe(u32 n) {
    u32 index = n;
    Entry *entry;
    entry = (Entry *)((u32)(index * sizeof(Entry)) + (u32)table);
    consume(entry);
}"""
    shift = 'sll $v1, $v0, 1'
    rows = [('o', '', shift)]
    rows += measured(('lui $a0, %hi(table)', 'lw $a0, %lo(table)($a0)'))
    rows += [('o', shift, '')]
    rows += measured(('addu $v1, $v1, $v0', 'sll $v1, $v1, 2', 'addu $v1, $v1, $a0'))
    [(family, candidate)] = variants(source, 'probe', '', rows)
    assert family == 'measured_volatile_table_base'
    assert candidate.index('__repair_table_base = table;') < candidate.index('index * sizeof(Entry)')
    assert not variants(source.replace('volatile ', ''), 'probe', '', rows)
    assert not variants(source.replace('(u32)table', '(u32)other'), 'probe', '', rows)


def test_nonnull_call_result_leaves_the_store_and_guard_on_the_original_result():
    source = """void probe(void *record, int size) {
    void *result;
    result = allocate(record, size);
    M2C_FIELD(record, void **, 8) = result;
    if (result != NULL) {
        int bits = M2C_FIELD(result, s32 *, 0);
        M2C_FIELD(result, s32 *, 4) = bits | M2C_FIELD(result, s32 *, 8);
    }
}"""
    rows = measured(('jal allocate', 'move $a0, $s0'))
    rows += [
        ('o', '', 'move $a1, $v0'),
        ('r', 'beqz $v0, 0xd4', 'beqz $a1, 0xd4'),
        ('r', 'sw $v0, 8($s0)', 'sw $a1, 8($s0)'),
        ('o', 'move $a1, $v0', ''),
    ]
    [(family, candidate)] = variants(source, 'probe', '', rows)
    assert family == 'measured_nonnull_call_result'
    assert 'if (result != NULL) {\n        void *__repair_nonnull_result = result;' in candidate
    assert candidate.count('M2C_FIELD(__repair_nonnull_result,') == 3
    assert not variants(source.replace('void **, 8', 'void **, 12'), 'probe', '', rows)
    assert not variants(source.replace('int bits', 'consume(result); int bits'), 'probe', '', rows)


def test_initial_record_pointer_requires_a_fresh_reload_before_each_later_store():
    source = """int probe(void *owner) {
    void *record;
    int ok;
    u32 word;
    record = M2C_FIELD(owner, void **, 4);
    ok = 1;
    if (record != NULL) {
        word = *(u32 *)((s8 *)record + 0x10);
        if (M2C_FIELD(record, u8 *, 0x11) != 0x6b) {
            record = M2C_FIELD(owner, void **, 4);
            M2C_FIELD(record, u32 *, 0x10) = word;
        }
    }
    return ok;
}"""
    rows = [
        (' ', 'move $a3, $a0', 'move $a3, $a0'),
        ('r', 'lw $v0, 4($a3)', 'lw $a1, 4($a3)'),
        (' ', 'addiu $t0, $zero, 1', 'addiu $t0, $zero, 1'),
        ('r', 'beqz $v0, 0xd8', 'beqz $a1, 0xd8'),
        (' ', 'nop', 'nop'),
        ('r', 'lbu $v1, 0x11($v0)', 'lbu $v1, 0x11($a1)'),
        ('r', 'lw $a0, 0x10($v0)', 'lw $a0, 0x10($a1)'),
    ]
    [(family, candidate)] = variants(source, 'probe', '', rows)
    assert family == 'measured_initial_record_pointer'
    assert 'if (__repair_initial_record != NULL)' in candidate
    assert 'M2C_FIELD(record, u32 *, 0x10) = word;' in candidate
    assert not variants(source.replace('    return ok;', '    return record != NULL;'), 'probe', '', rows)
    assert not variants(source.replace('            record =', '            if (word) record ='), 'probe', '', rows)
    assert not variants(source.replace('            record =', '            if (word)\n                record ='), 'probe', '', rows)


def test_shade_clamp_storage_preserves_the_packing_local():
    source = """void probe(void *owner, s32 value, s32 adjusted) {
    s32 shade;
    void *record;
    shade = value;
    if (shade != 0xFF) {
        if (adjusted >= 0) {
            shade += 0x10;
            if (adjusted >= 0x100) {
                shade = 0xFF;
            }
        } else {
            shade = 0;
        }
        record = M2C_FIELD(owner, void **, 0x10);
        shade = shade & 0xFF;
        save(record, shade);
    }
}"""
    rows = [
        ('r', 'lbu $v1, 0x10($v0)', 'lbu $a0, 0x10($v0)'),
        *measured(('nop', 'nop')),
        ('r', 'addiu $v0, $v1, 0x10', 'addiu $a2, $a0, 0x10'),
        ('r', 'bltz $v0, 0x90', 'bltz $a2, 0x90'),
        ('r', 'slti $v0, $v0, 0x100', 'slti $v0, $a2, 0x100'),
        *measured(('nop',) * 6),
        ('r', 'andi $v1, $v1, 0xff', 'andi $a0, $a0, 0xff'),
        *measured(('jr $ra',)),
    ]
    [(family, candidate)] = variants(source, 'probe', '', rows)
    assert family == 'measured_shade_clamp_storage'
    assert 'if (shade != 0xFF) {\n        s32 __repair_clamped_shade = shade;' in candidate
    assert 'shade = __repair_clamped_shade & 0xff;' in candidate
    assert not variants(source.replace('s32 shade;', 's32 shade; use(&shade);'), 'probe', '', rows)
    assert not variants(source.replace('shade += 0x10;', 'shade += 0x11;'), 'probe', '', rows)


def test_unsigned_table_guard_requires_two_unsigned_loads_from_the_same_table():
    source = """extern char table[];
s32 probe(s32 base, s16 index) {
    s32 offset;
    s32 result;
    offset = index * 0xE8;
    result = 1;
    if (M2C_FIELD((base + (*(table + offset) * 2)), s16 *, 0x1BC) == 0) {
        result = 1;
        if ((check(base, index) << 0x10) == 0) {
            result = *(table + offset) == 0;
        }
    }
    return result;
}
"""
    rows = measured((
        'addiu $sp, $sp, -24', 'sll $a1, $a1, 16', 'sra $a1, $a1, 16',
        'sll $v0, $a1, 3', 'subu $v0, $v0, $a1', 'sll $v0, $v0, 2',
        'addu $v0, $v0, $a1', 'sw $s0, 16($sp)', 'sll $s0, $v0, 3',
        'sw $ra, 20($sp)', 'lui $v0, %hi(table)', 'addu $v0, $v0, $s0',
    ))
    load = ('|', 'lbu $v0, %lo(table)($v0)', 'lb $v0, %lo(table)($v0)')
    rows += [load]
    rows += measured((
        'sll $v0, $v0, 1', 'addu $v0, $a0, $v0', 'lh $v0, 0x1bc($v0)',
        'bnez $v0, 0x6c', 'addiu $v0, $zero, 1', 'jal check', 'nop', 'sll $v0, $v0, 16',
        'bnez $v0, 0x6c', 'addiu $v0, $zero, 1', 'lui $v0, %hi(table)', 'addu $v0, $v0, $s0',
    ))
    rows += [load] + measured(('sltiu $v0, $v0, 1', 'lw $ra, 20($sp)', 'jr $ra'))
    [(family, candidate)] = variants(source, 'probe', '', rows)
    assert family == 'measured_unsigned_table_guard'
    assert 'extern u8 table[];' in candidate
    assert '((s32)(u32)base + (table[offset] << 1))' in candidate
    assert 'return *(table + offset) == 0;' in candidate
    assert not variants(source, 'probe', 'extern char table[];', rows)
    assert not variants(source.replace('check(base, index)', 'other(base, index)'), 'probe', '', rows)


def test_byte_pair_scan_requires_both_parameter_masks_and_the_packed_load():
    source = """s32 probe(s32 base, s32 low, s32 high) {
    s32 cursor;
    s32 index;
    u16 packed;
    cursor = 1;
    index = 1 & 0xFF;
again:
    packed = M2C_FIELD(((index * 2) + base), u16 *, 0x138);
    if ((packed & 0xFF) != (low & 0xFF)) {
        cursor += 1;
        goto next;
    }
    if ((packed >> 8) != (high & 0xFF)) {
        cursor += 1;
next:
        index = cursor & 0xFF;
        if ((u32) (cursor & 0xFF) >= 0x1EU) {
            return 0;
        }
        goto again;
    }
    return 1;
}
"""
    rows = measured((
        'addiu $a3, $zero, 1', 'andi $a1, $a1, 255', 'andi $a2, $a2, 255',
        'andi $v0, $a3, 255', 'sll $v0, $v0, 1', 'addu $v0, $v0, $a0',
        'lhu $v1, 312($v0)', 'andi $v0, $v1, 255', 'bnel $v0, $a1, 60',
        'addiu $a3, $a3, 1', 'srl $v0, $v1, 8', 'bnel $v0, $a2, 60',
        'addiu $a3, $a3, 1', 'j probe+0x50', 'addiu $v0, $zero, 1',
        'andi $v0, $a3, 255', 'sltiu $v0, $v0, 30', 'bnez $v0, 16',
        'andi $v0, $a3, 255', 'move $v0, $zero', 'jr $ra', 'nop',
    ))
    rows[1] = ('|', rows[1][1], 'addiu $v1, $zero, 1')
    [(family, candidate)] = variants(source, 'probe', '', rows)
    assert family == 'measured_byte_pair_scan'
    assert 'probe(s32 base, u8 low, u8 high)' in candidate
    assert candidate.count('index++; continue;') == 2
    assert not variants(source, 'probe', 's32 probe(s32, s32, s32);', rows)
    assert not variants(source.replace('0x138', '0x134'), 'probe', '', rows)


def test_volatile_float_pair_preserves_both_reads_and_the_original_local():
    source = """extern void *table[];
void probe(s32 i) {
    volatile f32 values[4];
    f32 pitch;
    void *volatile *cursor;
    cursor = &table[i];
    values[0] = (*(f32 *)((char *)(*cursor) + 0x34));
    pitch = (*(f32 *)((char *)(*cursor) + 0x38));
    values[2] = 0;
    values[1] = pitch;
    consume(pitch);
}"""
    rows = [
        (' ', 'swc1 $f0, 0x28($sp)', 'swc1 $f0, 0x28($sp)'),
        ('r', 'lw $v0, ($s4)', 'lw $v0, ($s3)'),
        ('r', 'lwc1 $f0, 0x38($v0)', 'lwc1 $f2, 0x38($v0)'),
        (' ', 'sw $zero, 0x30($sp)', 'sw $zero, 0x30($sp)'),
        ('r', 'swc1 $f0, 0x2c($sp)', 'swc1 $f2, 0x2c($sp)'),
    ]
    [(family, fixed)] = variants(source, 'probe', '', rows)
    assert family == 'measured_volatile_float_pair'
    assert fixed.count('(char *)(*cursor)') == 2
    assert 'pitch = __repair_loaded_float;' in fixed
    assert not variants(source.replace('volatile f32 values', 'f32 values'), 'probe', '', rows)
    assert not variants(source.replace('0x38', '0x3C'), 'probe', '', rows)


def test_swap_byte_store_parameter_widths_from_prologue():
    source = 'void f(void *obj, int k, u8 x, s32 y) { obj->x = x; obj->y = y; }'
    ops = ['sw $s4, 0x28($sp)', 'move $s4, $a2', 'sw $s7, 0x34($sp)', 'move $s7, $a3']
    rows = measured(['addiu $sp, $sp, -0x40'])
    rows += [(mark, left, right) for mark, left, right in zip('irir', ops, ops[2:] + ops[:2])]
    rows += measured(['jal prep', 'nop', 'sb $s4, 4($s1)', 'sb $s7, 1($s1)'])
    assert variants(source, 'f', '', rows) == [
        ('measured_parameter_store_widths', source.replace('u8 x, s32 y', 's32 x, u8 y')),
    ]
    assert variants(source.replace('obj->y = y;', 'obj->y = y; use(y);'), 'f', '', rows) == []
    assert variants(source, 'f', 'void f(void *, int, u8, s32);', rows) == []
    assert variants(source, 'f', '', rows[:-1]) == []


def test_copy_stacked_formal_after_first_call():
    source = """int f(int a, int b, int c, int d, int options) {
    unsigned int bits;
    bits = options;
    setup(a, b);
    if (check(c, d)) {
        return bits & 1;
    }
    return 0;
}
"""
    rows = measured(('addiu $sp, $sp, -0x20', 'lw $s6, 0x30($sp)', 'jal setup', 'nop',
                     'jal check', 'nop', 'sll $v0, $v0, 0x18', 'beqz $v0, 0x30'))
    rows.append(('<', 'move $s2, $s6', ''))
    candidate = source.replace('    bits = options;\n', '').replace(
        '    setup(a, b);\n', '    setup(a, b);\n    bits = options;\n')
    assert variants(source, 'f', '', rows) == [('measured_delay_stack_formal_copy', candidate)]
    assert not variants(source.replace('setup(a, b)', 'setup(bits, b)'), 'f', '', rows)
    assert not variants(source.replace('unsigned int bits', 'volatile unsigned int bits'), 'f', '', rows)
    assert not variants(source.replace('setup(a, b)', 'setup(&options, b)'), 'f', '', rows)
    assert not variants(source, 'f', '', rows[:4] + measured(('move $s6, $v0',)) + rows[4:])


def test_split_flag_word_when_target_uses_both_saved_registers():
    source = """int f(int options) {
    unsigned int flags;
    int result;
    flags = options;
    if ((check() << 24) != 0) {
        result = make();
        if (flags & 2) { result++; }
        if (flags & 1) { result--; }
        return result;
    }
    return 0;
}
"""
    rows = measured(('jal check', 'nop', 'sll $v0, $v0, 24', 'beqz $v0, 80'))
    rows += [('<', 'move $s2, $s6', ''),
             ('r', 'andi $v0, $s6, 2', 'andi $v0, $s3, 2'),
             ('r', 'andi $v0, $s2, 1', 'andi $v0, $s3, 1')]
    candidate = source.replace('    unsigned int flags;\n', '    unsigned int flags;\n    u32 __repair_mask_flags;\n')
    candidate = candidate.replace('        result = make();', '        do { __repair_mask_flags = flags; } while (0);\n'
                                  '        result = make();').replace('if (flags & 1)', 'if (__repair_mask_flags & 1)')
    assert variants(source, 'f', '', rows) == [('measured_split_saved_flag_mask', candidate)]
    assert not variants(source, 'f', '', rows[:-1])
    assert not variants(source.replace('result = make();', 'result = use(&flags);'), 'f', '', rows)
    assert not variants(source.replace('return result;', 'goto exit;'), 'f', '', rows)


def test_capture_invariant_float_before_loop_cursor_setup():
    source = """extern f32 bias;
void f(int count) {
    Point points[8];
    Point *out;
    int i;
    if (count) {
        out = points;
        i = 0;
        do {
            out->x = bias + i;
            out->y = bias - i;
            out++;
            i++;
        } while (i < count);
    }
}
"""
    cursor, zero = 'addiu $a0, $sp, 0x18', 'move $a1, $zero'
    rows = [('o', '', cursor), ('o', '', zero)]
    rows += measured(('lui $at, %hi(bias)', 'lwc1 $f4, %lo(bias)($at)'))
    rows += [('o', cursor, ''), ('o', zero, '')]
    expected = source.replace('out = points;', 'f32 __repair_loop_float = bias;\n        out = points;')
    expected = expected.replace('= bias +', '= __repair_loop_float +').replace('= bias -', '= __repair_loop_float -')
    assert variants(source, 'f', '', rows) == [('measured_capture_loop_float', expected)]
    assert not variants(source.replace('extern f32 bias;', 'extern volatile f32 bias;'), 'f', '', rows)
    assert not variants(source.replace('out++;', 'touch(out); out++;'), 'f', '', rows)
    assert not variants(source.replace('out++;', 'out = elsewhere; out++;'), 'f', '', rows)
    assert not variants(source.replace('out++;', '*elsewhere = 0; out++;'), 'f', '', rows)
    assert not variants(source, 'f', '', rows[:-1])
