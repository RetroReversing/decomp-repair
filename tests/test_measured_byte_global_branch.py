from decomprepair.measured_byte_global_branch import variants

SOURCE = '''extern u8 counter;
void advance(void) {
    u8 result;
    result = 0xFF;
    if ((u8) counter < 0xFFU) {
        result = counter + 5;
    }
    counter = result;
}
'''
TARGET = ['lui $v1, %hi(counter)', 'addiu $v1, $v1, %lo(counter)', 'lbu $v0, ($v1)',
          'sltiu $v0, $v0, 0xff', 'beqz $v0, 0x20', 'addiu $v0, $zero, 0xff',
          'lbu $v0, ($v1)', 'addiu $v0, $v0, 5', 'jr $ra', 'sb $v0, ($v1)']
CANDIDATE = ['lui $v0, %hi(counter)', 'lbu $v0, %lo(counter)($v0)',
             'lui $at, %hi(counter)', 'sb $v1, %lo(counter)($at)']
ROWS = [('r', TARGET[i] if i < len(TARGET) else '',
         CANDIDATE[i] if i < len(CANDIDATE) else '') for i in range(10)]


def test_explicit_branch_and_pointer():
    result = variants(SOURCE, 'advance', '', ROWS)
    assert len(result) == 1
    assert 'if (*__repair_byte_ptr >= 0xFFU)' in result[0][1]
    assert '*__repair_byte_ptr = result;' in result[0][1]


def test_rejects_nonmatching_evidence_and_source():
    assert not variants(SOURCE, 'advance', '', [('r', 'nop', right) for _, _, right in ROWS])
    assert not variants(SOURCE.replace('+ 5', '+ 6'), 'advance', '', ROWS)
    assert not variants(SOURCE.replace('extern u8', 'extern volatile u8'), 'advance', '', ROWS)
    assert not variants(SOURCE.replace('result = 0xFF;', '/* note */ result = 0xFF;'), 'advance', '', ROWS)
