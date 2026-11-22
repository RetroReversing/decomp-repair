from decomprepair.measured_byte_search_loop import variants

SOURCE = '''u8 *scan(u8 *str, s32 ch) {
    s32 needle;
    u8 *cursor;
    u8 *result;
    u8 byte;
    cursor = str;
    byte = *cursor;
    needle = ch & 0xFF;
    result = cursor;
    if ((byte & 0xFF) != needle) {
loop_1:
        cursor += 1;
        if (byte == 0) {
            return NULL;
        }
        byte = *cursor;
        result = cursor;
        if (byte == needle) {
            /* Duplicate return node #4. Try simplifying control flow for better match */
            return result;
        }
        goto loop_1;
    }
    return result;
}
'''
T = ['lbu $v1, ($a0)', 'andi $a1, $a1, 0xff', 'andi $v0, $v1, 0xff', 'beq $v0, $a1, 0x30',
     'move $v0, $a0', 'bnez $v1, 0x24', 'addiu $a0, $a0, 1', 'j scan+0x30', 'move $v0, $zero',
     'lbu $v1, ($a0)', 'bne $v1, $a1, 0x14', 'move $v0, $a0']
C = ['move $v0, $a0', 'lbu $a0, ($v0)', 'andi $a1, $a1, 0xff', 'beq $a0, $a1, 0x30', 'move $v1, $v0']
ROWS = [('r', T[i] if i < len(T) else '', C[i] if i < len(C) else '') for i in range(len(T))]


def test_reconstructs_byte_search_and_zero_check():
    result = variants(SOURCE, 'scan', '', ROWS)
    assert len(result) == 1
    assert 'u8 needle;' in result[0][1]
    assert 'while (byte != needle)' in result[0][1]
    assert result[0][1].index('if (byte == 0)') < result[0][1].index('cursor += 1;')
    assert 'return cursor;' in result[0][1]


def test_requires_complete_pattern_and_does_not_remove_user_comments():
    assert not variants(SOURCE, 'scan', '', [('r', x, x) for x in T])
    assert not variants(SOURCE.replace('byte == 0', 'byte == 1'), 'scan', '', ROWS)
    assert not variants(SOURCE.replace('s32 needle;', 'volatile s32 needle;'), 'scan', '', ROWS)
    assert not variants(SOURCE.replace('return result;', '/* retain */ return result;', 1), 'scan', '', ROWS)
