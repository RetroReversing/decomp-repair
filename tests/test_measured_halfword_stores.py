from decomprepair.measured_halfword_stores import variants


def test_three_halfword_stores_share_literal_only_in_the_accepted_arm():
    text = """
lui $v1, %hi(mode)
lw $v1, %lo(mode)($v1)
addiu $v0, $zero, 2
bne $v1, $v0, 64
nop
lui $v0, %hi(mode_ptr)
lw $v0, %lo(mode_ptr)($v0)
lhu $v0, 14($v0)
bne $v0, $v1, 64
addiu $v0, $zero, 80
lui $at, %hi(first)
sh $v0, %lo(first)($at)
lui $at, %hi(second)
sh $v0, %lo(second)($at)
j f+92
nop
lw $v0, 12($a0)
lui $at, %hi(first)
sh $v0, %lo(first)($at)
lw $v0, 16($a0)
lui $at, %hi(second)
sh $v0, %lo(second)($at)
lw $v0, 20($a0)
lui $at, %hi(third)
sh $v0, %lo(third)($at)
jr $ra
nop
"""
    rows = [(' ', op, op) for op in text.strip().splitlines()]
    rows.insert(9, ('>', '', 'addiu $a1, $zero, 80'))
    source = '''
void f(void *obj) {
    s32 value;
    if ((mode == 2) && (value = 80, (M2C_FIELD(M2C_FIELD(&ctx, void **, 36), u16 *, 14) == mode))) {
        M2C_FIELD(&output, s16 *, 10) = 80;
        M2C_FIELD(&output, s16 *, 12) = 80;
    } else {
        M2C_FIELD(&output, s16 *, 10) = (s16) M2C_FIELD(obj, s32 *, 12);
        M2C_FIELD(&output, s16 *, 12) = (s16) M2C_FIELD(obj, s32 *, 16);
        value = M2C_FIELD(obj, s32 *, 20);
    }
    M2C_FIELD(&output, s16 *, 14) = (s16) value;
}
'''
    addresses = {'ctx': 0x80000000, 'mode_ptr': 0x80000024, 'output': 0x80001000,
                 'first': 0x8000100a, 'second': 0x8000100c, 'third': 0x8000100e}
    [(family, fixed)] = variants(source, 'f', rows, addresses.get)
    assert family == 'measured_shared_halfword_literal'
    assert '(value = M2C_FIELD(M2C_FIELD(&ctx, void **, 36), u16 *, 14)) == mode' in fixed
    assert 'value = 80;\n        M2C_FIELD(&output, s16 *, 10) = value;' in fixed
    assert 'M2C_FIELD(&output, s16 *, 14) = (s16) value;' in fixed
    assert not variants(source, 'f', rows)
    assert not variants(source.replace('s32 *, 20', 's32 *, 24'), 'f', rows, addresses.get)
    addresses['third'] += 2
    assert not variants(source, 'f', rows, addresses.get)
