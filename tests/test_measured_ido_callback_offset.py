from decomprepair.measured_ido_callback_offset import variants

SOURCE = '''void example(s32 *arg, s32 value) {
    register void *cursor;
    cursor = M2C_FIELD(arg, void **, 0x28);
    M2C_FIELD(cursor, M2C_UNK (**)(void *), 0x64)(M2C_FIELD(cursor, s16 *, 0x60) + arg);
}
'''
TARGET = ['lw $t9, 0x28($sp)', 'lw $s0, 0x28($t9)', 'lh $t0, 0x60($s0)',
          'addu $a0, $t0, $t9', 'lw $t9, 0x64($s0)', 'jalr $t9']
CANDIDATE = ['lh $t0, 0x60($s0)', 'sll $t1, $t0, 2', 'lw $t2, 0x28($sp)',
             'addu $a0, $t1, $t2', 'lw $t9, 0x64($s0)', 'jalr $t9']
ROWS = [('r', TARGET[i] if i < len(TARGET) else '', CANDIDATE[i]) for i in range(len(CANDIDATE))]


def test_callback_offset_uses_byte_address_and_ido_evaluation_order():
    result = variants(SOURCE, 'example', '', ROWS)
    assert len(result) == 1
    assert 'cursor = M2C_FIELD(arg, void **, 0x28)' in result[0][1]
    assert '+ (s8 *) arg' in result[0][1]


def test_requires_matching_evidence_and_exclusive_temporary():
    assert not variants(SOURCE, 'example', '', [('r', 'nop', c) for _, _, c in ROWS])
    assert not variants(SOURCE.replace('0x60', '0x62'), 'example', '', ROWS)
    assert not variants(SOURCE.replace('register void', 'volatile void'), 'example', '', ROWS)
    assert not variants(SOURCE.replace('\n}', '\n    use(cursor);\n}'), 'example', '', ROWS)
