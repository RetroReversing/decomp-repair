from decomprepair.short_leaf_drafts import applies, variants


def test_float_square_root_leaf_replaces_a_self_call_with_the_builtin():
    source = 'f32 math_wrapper(f32 x) { return math_wrapper(x); }\n'
    asm = 'jr $ra\nsqrt.s $fv0, $fa0\n'
    [(family, fixed)] = variants(source, 'math_wrapper', asm)
    assert family == 'measured_sqrt_leaf'
    assert fixed == source.replace('return math_wrapper', 'return __builtin_sqrtf')
    assert not variants(source, 'math_wrapper', asm.replace('$fa0', '$fa1'))
    assert not variants(source, 'math_wrapper', asm, '#define __builtin_sqrtf use_macro')


def test_halfword_store_uses_unsigned_field_only_for_the_observed_literal():
    source = 'void f(void) { M2C_FIELD(&sState, s16 *, 0xC) = 0xABCD; }\n'
    asm = '''
ori $v0, $zero, 0xABCD
lui $at, %hi(sState + 12)
jr $ra
sh $v0, %lo(sState + 12)($at)
'''
    [(family, fixed)] = variants(source, 'f', asm)
    assert family == 'measured_unsigned_halfword_store'
    assert fixed == source.replace('s16', 'u16')
    assert not variants(source.replace('0xC)', '0xE)'), 'f', asm)
    assert not variants(source.replace('0xABCD', '0xABCE'), 'f', asm)
    assert not variants(source, 'f', asm, 'extern volatile s32 sState;')
    assert not applies(asm.replace('%lo(sState + 12)', '%lo(other + 12)'))


def test_mask_leaf_preserves_original_load_and_boolean_semantics():
    source = '''
s32 f(void) {
    return (M2C_FIELD(&state, s32 *, 4) & 0x4000) != 0;
}
'''
    asm = '''
lui $v0, %hi(state + 4)
lw $v0, %lo(state + 4)($v0)
andi $v0, $v0, 0x4000
jr $ra
sltu $v0, $zero, $v0
'''
    [(family, fixed)] = variants(source, 'f', asm)
    assert family == 'measured_mask_boolean_return'
    assert '    if ((M2C_FIELD(&state, s32 *, 4) & 0x4000) != 0) return 1;\n    return 0;' in fixed
    assert not variants(source.replace('0x4000', '0x40'), 'f', asm)
    assert not variants(source, 'f', asm.replace('sltu $v0, $zero, $v0', 'slt $v0, $zero, $v0'))


def test_framed_constant_takes_the_existing_leaf_frame_rule_for_exact_size():
    source = 's32 f(void) { return 1; }\n'
    asm = 'addiu $sp, $sp, -24\naddiu $v0, $zero, 1\njr $ra\naddiu $sp, $sp, 24'
    [(family, fixed)] = variants(source, 'f', asm)
    assert family == 'unused_frame_local'
    assert 'u8 __repair_frame[24];' in fixed
    assert not variants(source.replace('return 1', 'return 2'), 'f', asm)
    assert not variants(source, 'f', asm.removesuffix('24') + '16')


def test_empty_varargs_leaf_requires_all_four_registers_at_home():
    source = 'void f(s32 first, M2C_UNK a, M2C_UNK b, M2C_UNK c) { }\n'
    asm = 'sw $a0, ($sp)\nsw $a1, 4($sp)\nsw $a2, 8($sp)\njr $ra\nsw $a3, 12($sp)'
    assert variants(source, 'f', asm) == [('varargs_signature', 'void f(s32 first, ...) { }\n')]
    assert not variants(source, 'f', asm.replace('$a3, 12', '$a3, 16'))
    assert not variants(source.replace('{ }', '{ use(a); }'), 'f', asm)
