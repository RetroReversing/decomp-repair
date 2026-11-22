from decomprepair.measured_byte_fallback_return import variants

SOURCE = '''s32 fold(s32 ch) {
    s32 byte;
    s32 result;
    if ((u32) ((ch - 0x41) & 0xFF) < 0x1BU) {
        return (ch + 0x20) & 0xFF;
    }
    byte = ch & 0xFF;
    result = 0x2F;
    if (byte != 0x5C) {
        result = byte;
    }
    return result;
}
'''
T = ['addiu $v0, $a0, -0x41', 'andi $v0, $v0, 0xff', 'sltiu $v0, $v0, 0x1b', 'beqz $v0, 0x20',
     'move $v1, $a0', 'addiu $v0, $a0, 0x20', 'j fold+0x34', 'andi $v0, $v0, 0xff',
     'andi $a0, $v1, 0xff', 'addiu $v1, $zero, 0x5c', 'beq $a0, $v1, 0x34',
     'addiu $v0, $zero, 0x2f', 'move $v0, $a0']
C = ['addiu $v0, $a0, -0x41', 'andi $v0, $v0, 0xff', 'sltiu $v0, $v0, 0x1b', 'beqz $v0, 0x1c',
     'addiu $v0, $a0, 0x20', 'j fold+0x34']
ROWS = [('r', T[i] if i < len(T) else '', C[i] if i < len(C) else '') for i in range(len(T))]


def test_uses_byte_local_and_direct_fallback():
    result = variants(SOURCE, 'fold', '', ROWS)
    assert len(result) == 1
    assert 'u8 byte;' in result[0][1]
    assert 'if (byte == 0x5C)' in result[0][1]
    assert 'return byte;' in result[0][1]


def test_requires_evidence_and_complete_unmodified_body():
    assert not variants(SOURCE, 'fold', '', [('r', x, x) for x in T])
    assert not variants(SOURCE.replace('0x5C', '0x5D'), 'fold', '', ROWS)
    assert not variants(SOURCE.replace('s32 byte;', 'volatile s32 byte;'), 'fold', '', ROWS)
    assert not variants(SOURCE.replace('return result;', 'touch(); return result;'), 'fold', '', ROWS)
