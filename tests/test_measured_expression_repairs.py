from decomprepair.measured_expression_repairs import variants


def rows(a,b):
    return [(' ' if x==y else 'r',x,y) for x,y in zip(a.split('|'),b.split('|'),strict=True)]


def test_signed_bit_test_keeps_original_load():
    source = 's32 f(void) { s32 status = *(volatile s32 *)0x8000; return (status & 0x80000000U) != 0; }'
    diff = rows('jr $ra|slti $v0, $v0, 0','jr $ra|srl $v0, $v0, 0x1f')
    assert variants(source,'f','',diff) == [('measured_sign_test',source.replace('& 0x80000000U','>> 31'))]
    assert not variants(source.replace('s32 status','u32 status'),'f','',diff)
    assert not variants(source,'f','',diff[1:])


def test_halfword_member_retains_the_measured_pointer_advance():
    header = 'extern u16 *p; typedef struct { u16 field_0; u8 pad[10]; u16 field_C; } R;'
    source = 'void f(void) { again: p += 6; if (((R*)p)->field_C != 0) goto again; }'
    diff = rows('lhu $v1, 0xc($a1)|addiu $v0, $a1, 12','lhu $v1, 0x18($a1)|addiu $v0, $a1, 12')
    assert variants(source,'f',header,diff) == [('measured_advanced_field',source.replace('field_C','field_0'))]
    assert not variants(source, 'f', header.replace('u16 field_0','u8 field_0'), diff)
    assert not variants(source.replace('+= 6','+= 7'),'f',header,diff)


def test_scaled_expression_needs_a_bounded_input_and_a_matching_register_chain():
    source = ('void f(u16 x) { s32 n; n = x & 0xFFFF; if (n) { s32 scaled = n * 5; '
              's32 base = M2C_FIELD(obj, s32 *, 0xC); scaled = (scaled << 2) - 0x14; save(base+scaled); } }')
    target = 'sll $v0, $v1, 2|addu $v0, $v0, $v1|lw $v1, 0xc($a3)|sll $v0, $v0, 2|addiu $v0, $v0, -0x14|addu $v1, $v1, $v0'
    prior = 'sll $v0, $v1, 2|addu $v1, $v0, $v1|lw $v0, 0xc($a3)|sll $v1, $v1, 2|addiu $v1, $v1, -0x14|addu $v0, $v0, $v1'
    diff = rows(target,prior)
    expected = source.replace('n * 5','((n << 2) + n) << 2').replace('(scaled << 2)','scaled')
    assert variants(source,'f','',diff) == [('measured_scaled_expression',expected)]
    assert not variants(source.replace('x & 0xFFFF','x'),'f','',diff)
    assert not variants(source,'f','',rows(target.replace('-0x14','-0x15'),prior))


def test_float_conversion_stays_in_the_same_guard():
    source = ('f32 f(f32 x) { f32 value; f32 neg; s32 n; n = read(); '
              'if (n) { neg = -x; if ((value = (f32) (n >> 1)) < neg) value = neg; } return value; }')
    diff = rows('|mtc1 $v0, $f2|nop|cvt.s.w $f2, $f2|neg.s $f0, $f4|c.lt.s $f2, $f0',
                'neg.s $f0, $f4|mtc1 $v0, $f2|nop|cvt.s.w $f2, $f2||c.lt.s $f2, $f0')
    [(family,candidate)] = variants(source,'f','',diff)
    assert family=='measured_staged_negation'
    assert 'if (n) { do { value = (f32) (n >> 1); } while (0);' in candidate
    assert 'if (value < neg)' in candidate
    assert not variants(source.replace('f32 neg','volatile f32 neg'),'f','',diff)
    assert not variants(source,'f','',diff[:-1])


def test_byte_lane_merge_keeps_the_loaded_byte_live_for_the_high_lane():
    source = '''
void f(void *out, u8 *input, s32 n) {
    u8 pixel;
    pixel = *(input + n);
    M2C_FIELD(out, s32 *, 4) = (s32) (((~pixel & 0xFF) << 0x10) | (pixel | 0xFF000000));
}
'''
    code = [
        'lbu $a0, ($a0)',
        'nor $v0, $zero, $a0',
        'andi $v0, $v0, 0xff',
        'sll $v0, $v0, 0x10',
        'lui $v1, 0xff00',
        'or $a0, $a0, $v1',
        'or $v0, $v0, $a0',
        'sw $v0, 4($a2)',
    ]
    rows = [(' ', inst, inst) for inst in code]
    rows[5] = ('r', code[5], 'or $v0, $v0, $v1')
    [(family, fixed)] = variants(source, 'f', '', rows)
    assert family == 'measured_byte_lane_merge'
    assert 'u32 pixel;' in fixed
    assert 'pixel = (u8) *(input + n);' in fixed
    assert '__repair_inverted_byte = (~pixel & 0xFF) << 16;' in fixed
    assert 'pixel |= 0xFF000000;' in fixed
    assert 'M2C_FIELD(out, s32 *, 4) = __repair_inverted_byte | pixel;' in fixed
    assert not variants(source.replace('<< 0x10', '<< 0x8'), 'f', '', rows)
    assert not variants(source.replace('4) = (s32)', '8) = (s32)'), 'f', '', rows)
    assert not variants(source.replace('pixel =', 'keep(&pixel);\n    pixel ='), 'f', '', rows)
    assert not variants(source, 'f', '', rows[:-1])


def test_branch_field_updates_remove_the_unused_join_temporary():
    source = '''
void f(void *obj) {
    s32 temp;
    if (flag) {
        if (ready) notify();
        temp = M2C_FIELD(obj, s32 *, 12) & ~4;
    } else {
        temp = M2C_FIELD(obj, s32 *, 12) | 4;
    }
    M2C_FIELD(obj, s32 *, 12) = temp;
}
'''
    diff = rows(
        'addiu $v1, $zero, -5|lw $v0, 12($a0)|j f+0x38|and $v0, $v0, $v1|'
        'lw $v0, 12($a0)|ori $v0, $v0, 4|jr $ra|sw $v0, 12($a0)',
        'addiu $v0, $zero, -5|lw $v1, 12($a0)|j f+0x38|and $v0, $v1, $v0|'
        'lw $v0, 12($a0)|ori $v0, $v0, 4|jr $ra|sw $v0, 12($a0)',
    )
    [(family, fixed)] = variants(source, 'f', '', diff)
    assert family == 'measured_branch_field_update'
    assert 'M2C_FIELD(obj, s32 *, 12) &= ~4;' in fixed
    assert 'M2C_FIELD(obj, s32 *, 12) |= 4;' in fixed
    assert 'temp' not in fixed
    assert 'if (ready) notify();' in fixed
    assert not variants(source.replace('| 4;', '| 8;'), 'f', '', diff)
    assert not variants(source.replace('= temp;', '= temp;\n    record(temp);'), 'f', '', diff)
    assert not variants(source, 'f', '', diff[:-1] + [(' ', 'sw $v0, 16($a0)', 'sw $v0, 16($a0)')])


def test_common_store_keeps_the_temporary_used_only_on_a_sibling_path():
    source = '''
void f(void *obj) {
    s32 value;
    value = read();
    if (ready) {
        if (flag) {
            value = M2C_FIELD(obj, s32 *, 12) | 4;
        } else {
            value = M2C_FIELD(obj, s32 *, 12) & ~4;
        }
        M2C_FIELD(obj, s32 *, 12) = value;
        notify();
    } else {
        report(value);
    }
}
'''
    diff = rows('addiu $v1, $zero, -5|lw $v0, 12($a0)|j f+0x30|ori $v0, $v0, 4|'
                'lw $v0, 12($a0)|and $v0, $v0, $v1|sw $v0, 12($a0)',
                'addiu $v0, $zero, -5|lw $v0, 12($a0)|j f+0x30|ori $v1, $v0, 4|'
                'lw $v1, 12($a0)|and $v1, $v1, $v0|sw $v1, 12($a0)')
    [(family, fixed)] = variants(source, 'f', '', diff)
    assert family == 'measured_branch_field_update'
    assert 's32 value;' in fixed and 'report(value);' in fixed
    assert 'M2C_FIELD(obj, s32 *, 12) |= 4;' in fixed
    assert 'M2C_FIELD(obj, s32 *, 12) &= ~4;' in fixed
    assert not variants(source.replace('notify();', 'notify(value);'), 'f', '', diff)
    assert not variants(source.replace('value = read()', 'value = read(&value)'), 'f', '', diff)


def test_guarded_division_uses_the_parameter_and_keeps_the_earlier_store():
    source = '''
s32 f(s32 channel, s32 mode, s32 divisor) {
    s32 value;
    value = read(channel);
    M2C_FIELD(state, s32 *, 8) = value;
    value = divisor & 0xFF;
    if (value != 0) {
        M2C_FIELD(state, s32 *, 12) = (s32) (255 / value);
    } else {
        M2C_FIELD(state, s32 *, 12) = 255;
    }
    return 0;
}
'''
    prefix = 'sw $v1, 8($a3)|'
    suffix = '|nop|break 7|addiu $at, $zero, -1|'
    diff = rows(prefix + 'andi $a2, $a2, 0xff|beqz $a2, 0x84|addiu $v0, $zero, 255|'
                'div $zero, $v0, $a2|bnez $a2, 0x58' + suffix + 'bne $a2, $at, 0x70',
                prefix + 'andi $v1, $a2, 0xff|beqz $v1, 0x84|addiu $v0, $zero, 255|'
                'div $zero, $v0, $v1|bnez $v1, 0x58' + suffix + 'bne $v1, $at, 0x70')
    [(family, fixed)] = variants(source, 'f', '', diff)
    assert family == 'measured_divisor_store_order'
    assert 'M2C_FIELD(state, volatile s32 *, 8) = value;' in fixed
    assert 'divisor &= 0xFF;' in fixed and '255 / divisor' in fixed
    assert not variants(source.replace('return 0;', 'return divisor;'), 'f', '', diff)
    assert not variants(source.replace('FIELD(state, s32 *, 12)', 'FIELD(value, s32 *, 12)'), 'f', '', diff)
    assert not variants(source.replace('255 / value', '256 / value'), 'f', '', diff)


def test_mode_selects_defaults_in_the_two_arms_around_the_early_return():
    source = '''
void f(void *obj) {
    s32 value;
    u8 mode;
    void *state;
    state = M2C_FIELD(obj, void **, 72);
    mode = M2C_FIELD(state, u8 *, 3);
    value = 3;
    if (mode >= 5U) {
        value = 4;
        if (mode == 7) {
            M2C_FIELD(state, s32 *, 32) = 8;
            M2C_FIELD(M2C_FIELD(obj, void **, 92), s32 *, 108) = 0;
            M2C_FIELD(M2C_FIELD(obj, void **, 48), s32 *, 108) = 0;
            return;
        }
    }
    M2C_FIELD(state, s32 *, 32) = value;
}
'''
    setup = 'lw $v1, 72($a0)|'
    rest = ('|addiu $v0, $zero, 8|sw $v0, 32($v1)|lw $v0, 92($a0)|sw $zero, 108($v0)|'
            'lw $v0, 48($a0)|j f+0x40|sw $zero, 108($v0)|')
    diff = rows(
        setup + 'lbu $a1, 3($v1)|sltiu $v0, $a1, 5|bnez $v0, 0x3c|addiu $v0, $zero, 3|'
        'addiu $v0, $zero, 7|bne $a1, $v0, 0x3c|addiu $v0, $zero, 4' + rest + 'sw $v0, 32($v1)|jr $ra|nop',
        setup + 'lbu $a2, 3($v1)|sltiu $v0, $a2, 5|bnez $v0, 0x3c|addiu $a1, $zero, 3|'
        'addiu $v0, $zero, 7|bne $a2, $v0, 0x3c|addiu $a1, $zero, 4' + rest + 'sw $a1, 32($v1)|jr $ra|nop',
    )
    [(family, fixed)] = variants(source, 'f', '', diff)
    assert family == 'measured_mode_defaults'
    assert 'if (mode < 5U) {\n        value = 3;' in fixed
    assert '} else if (mode == 7)' in fixed
    assert 'return;\n    } else {\n        value = 4;' in fixed
    assert not variants(source.replace('return;', 'if (maybe) return;'), 'f', '', diff)
    assert not variants(source.replace('mode == 7', 'mode == 8'), 'f', '', diff)


def test_branch_constant_store_uses_the_condition_register():
    source = """\
extern s16 enabled;
extern s8 setting;
void f(void) {
    s8 value;
    value = 3;
    if (enabled == 0) {
        value = 5;
    }
    setting = value;
}
"""
    target = ('lui $v0, %hi(enabled)|lh $v0, %lo(enabled)($v0)|bnez $v0, 0x14|'
              'addiu $v0, $zero, 3|addiu $v0, $zero, 5|lui $at, %hi(setting)|sb $v0, %lo(setting)($at)')
    candidate = target.replace('addiu $v0', 'addiu $v1').replace('sb $v0', 'sb $v1')
    diff = rows(target, candidate)
    [(family, fixed)] = variants(source, 'f', '', diff)
    assert family == 'measured_branch_constant_store'
    assert 'if (enabled) {\n        setting = 3;\n    } else {\n        setting = 5;' in fixed
    assert not variants(source.replace('setting = value;', 'setting = value;\n    consume(value);'), 'f', '', diff)
    assert not variants(source.replace('setting = value;', 'other = value;'), 'f', '', diff)
    assert not variants(source, 'f', '#define setting set_value()', diff)
    assert not variants(source, 'f', '', rows(target.replace('0x14', '0x18'), candidate.replace('0x14', '0x18')))
