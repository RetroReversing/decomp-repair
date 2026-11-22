from decomprepair.measured_command_word_schedule import variants

SOURCE = '''void *build(void *obj, s32 n, s32 stride, void *out) {
    s32 x;
    s32 word;
    s32 scaled;
    x = n & 0xFFFF;
    scaled = (stride * 2) & 0xFFFF;
    word = (x << 0x10) | scaled;
    M2C_FIELD(out, s32 *, 0xc) = physical(obj + 8, word, scaled);
    M2C_FIELD(out, s32 *, 0x10) = (s32) ((M2C_FIELD(obj, u8 *, 0x2f) << 0x10) | (M2C_FIELD(obj, u16 *, 2) | 0x0e000000));
    M2C_FIELD(out, s32 *, 0x14) = physical(M2C_FIELD(obj, s32 *, 0x28));
    return out + 0x18;
}
'''
T = ['sll $a1, $a1, 0x10', 'sll $a2, $a2, 1', 'andi $a2, $a2, 0xffff', 'or $a1, $a1, $a2',
     'lbu $v0, 0x2f($s1)', 'lhu $v1, 2($s1)', 'lui $a0, 0xe00', 'sll $v0, $v0, 0x10',
     'or $v1, $v1, $a0', 'or $v0, $v0, $v1', 'addiu $s0, $s0, 0x18', 'move $v0, $s0']
C = ['sll $a2, $a2, 1', 'andi $a2, $a2, 0xffff', 'sll $a1, $a1, 0x10', 'or $a1, $a1, $a2',
     'lbu $v0, 0x2f($s1)', 'lhu $a0, 2($s1)', 'lui $v1, 0xe00', 'sll $v0, $v0, 0x10',
     'or $v0, $v0, $v1', 'or $v0, $v0, $a0', 'addiu $v0, $s0, 0x18']
ROWS = [('r', T[i] if i < len(T) else '', C[i] if i < len(C) else '') for i in range(len(T))]


def test_stages_end_and_reassociates_word():
    result = variants(SOURCE, 'build', '', ROWS)
    assert len(result) == 1
    assert '__repair_command_end = (char *)out + 0x18;' in result[0][1]
    assert 'return __repair_command_end;' in result[0][1]
    assert result[0][1].count('((stride * 2) & 0xFFFF)') == 2


def test_requires_measured_pattern_and_unchanged_arguments():
    assert not variants(SOURCE, 'build', '', [('r', x, x) for x in T])
    assert not variants(SOURCE.replace('0x2f', '0x30'), 'build', '', ROWS)
    assert not variants(SOURCE.replace('void *obj', 'volatile void *obj'), 'build', '', ROWS)
    assert not variants(SOURCE.replace('x = n', 'stride++; x = n'), 'build', '', ROWS)
