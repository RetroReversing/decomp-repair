from decomprepair.measured_indirect_command_records import variants

SOURCE = '''extern void *synth;
typedef struct { int field_0; int field_4; } Record;
s32 build(s32 input, void *dest) {
    void *first; void *second;
    ((Record*)dest)->field_0 = 0x020004E0;
    ((Record*)dest)->field_4 = 0x2E0;
    first = M2C_FIELD(M2C_FIELD(synth, void **, 0x3C), void *(**)(void *), 4)(dest + 8);
    second = first + 8;
    M2C_FIELD(first, s32 *, 0) = 0x0C007FFF;
    M2C_FIELD(first, s32 *, 4) = 0x07C004E0;
    M2C_FIELD(second, s32 *, 4) = 0x09300650;
    M2C_FIELD(first, s32 *, 8) = 0x0C007FFF;
    return second + 8;
}
'''
TARGET = ['lui $v1, %hi(synth)', 'lw $v0, 0x3c($v1)', 'lw $v0, 4($v0)', 'jalr $v0',
          'addiu $a1, $a1, 8', 'move $v1, $v0', 'move $a1, $v1', 'addiu $v1, $v1, 8',
          'lui $a2, 0xc00', 'ori $a2, $a2, 0x7fff', 'lui $a0, 0x7c0', 'ori $a0, $a0, 0x4e0',
          'lui $a3, 0x930', 'ori $a3, $a3, 0x650', 'addiu $v0, $v1, 8', 'sw $a2, ($a1)',
          'sw $a0, 4($a1)', 'sw $a2, ($v1)', 'lw $ra, 0x10($sp)', 'sw $a3, 4($v1)']
CANDIDATE = ['jalr $v0', 'addiu $a0, $a1, 8']
ROWS = [('r', TARGET[i] if i < len(TARGET) else 'nop',
         CANDIDATE[i] if i < len(CANDIDATE) else 'nop') for i in range(30)]


def test_recovers_forwarded_argument_and_record_cursor():
    result = variants(SOURCE, 'build', '', ROWS)
    assert len(result) == 1
    assert '(input, __repair_p + 1)' in result[0][1]
    assert '__repair_first = __repair_out++' in result[0][1]


def test_requires_live_entry_register_and_matching_commands():
    assert not variants(SOURCE, 'build', '', [('r', 'nop', right) for _, _, right in ROWS])
    assert not variants(SOURCE.replace('0x09300650', '0x09300651'), 'build', '', ROWS)
    assert not variants(SOURCE, 'build', 'typedef int __repair_cmd;', ROWS)
    assert not variants(SOURCE.replace('first = M2C_FIELD', '/* note */ first = M2C_FIELD'), 'build', '', ROWS)
