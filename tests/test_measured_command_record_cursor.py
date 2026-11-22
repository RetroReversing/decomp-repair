from decomprepair.measured_command_record_cursor import variants

SOURCE = '''extern void *synth;
typedef struct { int field_0; unsigned char pad_4[4]; int field_8; } Record;
void *make(void) {
    void *first; void *second;
    first = pull();
    ((Record*)first)->field_0 = 0x0D000000;
    second = first + 8;
    ((Record*)first)->field_8 = 0x062E0000;
    M2C_FIELD(second, s32 *, 4) = (s32) M2C_FIELD(synth, s32 *, 0x54);
    return second + 8;
}
'''
TARGET = ['jal pull', 'nop', 'move $v1, $v0', 'move $a0, $v1', 'lui $v0, 0xd00',
          'sw $v0, ($a0)', 'lui $a0, %hi(synth)', 'lw $a0, %lo(synth)($a0)',
          'addiu $v1, $v1, 8', 'lui $v0, 0x62e', 'sw $v0, ($v1)',
          'lw $a0, 0x54($a0)', 'addiu $v0, $v1, 8', 'lw $ra, 0x10($sp)', 'sw $a0, 4($v1)']
CANDIDATE = ['sw $v0, 8($v1)', 'addiu $v0, $v1, 0x10']
ROWS = [('r', TARGET[i] if i < len(TARGET) else 'nop',
         CANDIDATE[i] if i < len(CANDIDATE) else 'nop') for i in range(20)]


def test_recovers_two_word_cursor():
    result = variants(SOURCE, 'make', '', ROWS)
    assert len(result) == 1
    assert 'first = cmd++;' in result[0][1]
    assert 'cmd->w1 = *(u32 *) ((char *) synth + 0x54);' in result[0][1]


def test_requires_matching_target_and_layout():
    assert not variants(SOURCE, 'make', '', [('r', 'nop', right) for _, _, right in ROWS])
    assert not variants(SOURCE.replace('0x54', '0x58'), 'make', '', ROWS)
    assert not variants(SOURCE.replace('extern void *synth', 'extern volatile void *synth'), 'make', '', ROWS)
    assert not variants(SOURCE.replace('first = pull();', '/* note */ first = pull();'), 'make', '', ROWS)
