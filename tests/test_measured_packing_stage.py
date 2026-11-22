from decomprepair.measured_packing_stage import variants

SOURCE = '''void pack(void) {
    s32 acc;
    s32 index;
    u8 byte;
    acc = 0;
    index = 0;
    do {
        byte = get_byte(index);
        index += 1;
        acc = (acc * 0x10) | byte;
    } while (index < 8);
}
'''
TARGET = ['lbu $v0, ($v0)', 'sll $a2, $a2, 4', 'addiu $v1, $v1, 1', 'or $a2, $a2, $v0']
CANDIDATE = ['lbu $v1, ($v0)', 'addiu $a0, $a0, 1', 'sll $v0, $a2, 4', 'or $a2, $v0, $v1']
ROWS = [('r', a, b) for a, b in zip(TARGET, CANDIDATE)]


def test_stages_accumulator_before_counter():
    result = variants(SOURCE, 'pack', '', ROWS)
    assert len(result) == 1
    assert 'acc = acc * 0x10;\n        index += 1;\n        acc |= byte;' in result[0][1]


def test_requires_evidence_and_independent_local_variables():
    assert not variants(SOURCE, 'pack', '', [('r', a, a) for a in TARGET])
    assert not variants(SOURCE.replace('0x10', '0x20'), 'pack', '', ROWS)
    assert not variants(SOURCE.replace('s32 index;', 'volatile s32 index;'), 'pack', '', ROWS)
    assert not variants(SOURCE.replace('index = 0;', 'use(&index); index = 0;'), 'pack', '', ROWS)
