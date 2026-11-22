from decomprepair.measured_guarded_byte import variants

SOURCE = '''u32 advance();
u32 check(s32 start, u32 end, s8 *flag) {
    u32 cursor;
    cursor = advance();
    if (cursor >= end) {
        *flag = 0;
        cursor = end;
    } else if (*(s32 *)cursor == 0x5B) {
        *flag = 0;
    } else {
        *flag = 1;
    }
    return cursor;
}'''
T = ['jal advance', 'move $s1, $a2', 'move $a0, $v0', 'sltu $v0, $a0, $s0', 'bnez $v0, 56',
     'addiu $v0, $zero, 91', 'sb $zero, ($s1)', 'j check+80', 'move $a0, $s0',
     'lb $v1, ($a0)', 'bne $v1, $v0, 76', 'addiu $v0, $zero, 1']
ROWS = [(' ', x, x) for x in T]
ROWS[9] = ('|', 'lb $v1, ($a0)', 'lw $v1, ($a0)')


def test_recovers_signed_byte_and_preserves_branch_assignment():
    label, fixed = variants(SOURCE, 'check', '', ROWS)[0]
    assert label == 'measured_guarded_byte'
    assert '*(s8 *)cursor == 0x5B' in fixed
    assert 'do { cursor = end; } while (0);' in fixed
    assert 'cursor = advance();' in fixed


def test_requires_guard_load_width_marker_and_complete_source():
    assert not variants(SOURCE, 'check', '', [(' ', x, x) for x in T])
    assert not variants(SOURCE.replace('0x5B', '0x5C'), 'check', '', ROWS)
    assert not variants(SOURCE.replace('*flag = 0;', 'touch(); *flag = 0;'), 'check', '', ROWS)
    assert not variants(SOURCE.replace('s8 *flag', 'volatile s8 *flag'), 'check', '', ROWS)
    assert not variants(SOURCE, 'check', '#define cursor other', ROWS)
    assert not variants(SOURCE.replace('u32 advance();', 'u32 advance(s32);'), 'check', '', ROWS)
