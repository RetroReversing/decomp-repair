from decomprepair.measured_masked_halfword_read import variants

SOURCE = '''void walk(void *node) {
    if (((M2C_FIELD(node, s32 *, 0xC) & 0xFFFF0001) == 0x40001) ||
        ((u16) M2C_FIELD(node, s32 *, 0xC) != 4)) {
        send(node + 0x10);
    }
}
'''
TARGET = ['lw $v0, 0xc($s0)', 'and $v0, $v0, $s2', 'beq $v0, $s1, 0x58',
          'addiu $a0, $s0, 0x10', 'lhu $v0, 0xc($s0)', 'beq $v0, $s4, 0x64', 'nop']
CANDIDATE = ['lw $v1, 0xc($s0)', 'and $v0, $v1, $s2', 'beq $v0, $s1, 0x54',
             'andi $v0, $v1, 0xffff', 'beq $v0, $s4, 0x64', 'nop']
ROWS = [('r', TARGET[i] if i < len(TARGET) else 'nop',
         CANDIDATE[i] if i < len(CANDIDATE) else 'nop') for i in range(30)]


def test_reconstructs_target_read_width():
    result = variants(SOURCE, 'walk', '', ROWS)
    assert len(result) == 1
    assert 'M2C_FIELD(node, u16 *, 0xC) != 4' in result[0][1]
    assert 'M2C_FIELD(node, s32 *, 0xC) & 0xFFFF0001' in result[0][1]


def test_requires_matching_offsets_and_instructions():
    assert not variants(SOURCE.replace('u16) M2C_FIELD(node, s32 *, 0xC)',
                                       'u16) M2C_FIELD(node, s32 *, 0xE)'), 'walk', '', ROWS)
    assert not variants(SOURCE, 'walk', '', [('r', 'nop', right) for _, _, right in ROWS])
    assert not variants(SOURCE.replace('void *node', 'volatile void *node'), 'walk', '', ROWS)
    assert not variants(SOURCE.replace('(u16)', '/* width */ (u16)'), 'walk', '', ROWS)
