from decomprepair.measured_frameless_padding import variants

SOURCE = '''void fill(s8 *dst, s8 value, s32 count) {
    s32 index;
    index = count - 1;
    if (count != 0) {
        do { *dst = value; index -= 1; dst += 1; } while (index != -1);
    }
}'''
ROWS = [('<', 'addiu $sp, $sp, -8', ''),
        ('i', 'beqz $a2, 0x20', 'beqz $a2, 0x1c'),
        (' ', 'addiu $v0, $a2, -1', 'addiu $v0, $a2, -1'),
        (' ', 'addiu $v1, $zero, -1', 'addiu $v1, $zero, -1'),
        (' ', 'sb $a1, ($a0)', 'sb $a1, ($a0)'),
        (' ', 'addiu $v0, $v0, -1', 'addiu $v0, $v0, -1'),
        ('i', 'bne $v0, $v1, 0x10', 'bne $v0, $v1, 0xc'),
        (' ', 'addiu $a0, $a0, 1', 'addiu $a0, $a0, 1'),
        (' ', 'jr $ra', 'jr $ra'),
        ('|', 'addiu $sp, $sp, 8', 'nop')]


def test_reserves_the_target_frame():
    label, fixed = variants(SOURCE, 'fill', '', ROWS)[0]
    assert label == 'measured_frameless_padding'
    assert 's32 __repair_unused_frame[2];' in fixed


def test_requires_matching_body_and_balanced_leaf_frame():
    wrong_branch = list(ROWS)
    wrong_branch[1] = ('i', 'beqz $a2, 0x24', 'beqz $a2, 0x1c')
    assert not variants(SOURCE, 'fill', '', wrong_branch)
    assert not variants(SOURCE, 'fill', '', ROWS[:-1])
    different = list(ROWS)
    different[4] = ('r', 'sb $a1, ($a0)', 'sb $a2, ($a0)')
    assert not variants(SOURCE, 'fill', '', different)
    assert not variants(SOURCE.replace('s32 index;', 'volatile s32 index;'), 'fill', '', ROWS)
    assert not variants(SOURCE, 'fill', '#define __repair_unused_frame other', ROWS)
