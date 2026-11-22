from decomprepair.measured_byte_signature import variants

SOURCE = '''s32 check(void) {
    s32 result;
    result = 0;
    if ((M2C_FIELD(&state, u8 *, 16) == 0x44) && (M2C_FIELD(&state, u8 *, 17) == 0x45)) {
        result = M2C_FIELD(&state, u8 *, 18) == 0x1D;
    }
    return result;
}'''
T = ['lui $a0, %hi(first)', 'lbu $a0, %lo(first)($a0)', 'addiu $v1, $zero, 68', 'bne $a0, $v1, 56',
     'move $v0, $zero', 'lui $a0, %hi(second)', 'lbu $a0, %lo(second)($a0)', 'addiu $v1, $zero, 69',
     'bne $a0, $v1, 56', 'nop', 'lui $v0, %hi(third)', 'lbu $v0, %lo(third)($v0)',
     'xori $v0, $v0, 29', 'sltiu $v0, $v0, 1', 'jr $ra', 'nop']
ROWS = [('r', op, '') for op in T]
SYMBOLS = {'state': 100, 'first': 116, 'second': 117, 'third': 118}


def test_stages_each_byte_and_constant():
    label, fixed = variants(SOURCE, 'check', '', ROWS, SYMBOLS.get)[0]
    assert label == 'measured_byte_signature'
    assert '__repair_byte = M2C_FIELD(&state, u8 *, 16);' in fixed
    assert '__repair_expected = 0x44;' in fixed
    assert 'if (__repair_byte == __repair_expected)' in fixed
    assert 's32 check(void)' in fixed


def test_requires_target_symbols_constants_and_visible_source():
    assert not variants(SOURCE, 'check', '', ROWS, None)
    assert not variants(SOURCE, 'check', '', ROWS, {'state': 100, 'first': 116, 'second': 118, 'third': 119}.get)
    assert not variants(SOURCE.replace('0x44', '0x46'), 'check', '', ROWS, SYMBOLS.get)
    assert not variants(SOURCE.replace('result = 0;', 'touch(); result = 0;'), 'check', '', ROWS, SYMBOLS.get)
    assert not variants(SOURCE, 'check', '#define result shared', ROWS, SYMBOLS.get)
    assert not variants(SOURCE.replace('s32 result;', 'volatile s32 result;'), 'check', '', ROWS, SYMBOLS.get)
