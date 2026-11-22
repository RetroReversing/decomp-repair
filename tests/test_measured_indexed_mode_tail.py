from decomprepair.measured_indexed_mode_tail import variants

SOURCE = '''extern s32 table;
s8 choose(s32 arg, s32 key) {
    M2C_UNK mode;
    s32 idx;
    s8 result;
    void *entry;
    idx = arg & 0xFF;
    entry = (void *)(table); entry = (void *)((char *)entry + (s32)((idx * 0x14)));
    if (key == M2C_FIELD(entry, s32 *, 0x68)) {
        mode = 0x20000;
        goto done;
    }
    result = 0;
    if (key == M2C_FIELD(entry, s32 *, 0x6c)) {
        mode = 0x10000;
done:
        result = call(idx, mode);
    }
    return result;
}
'''
T = ['lui $v0, %hi(table)', 'lw $v0, %lo(table)($v0)', 'andi $a0, $a0, 0xff', 'sll $v1, $a0, 2',
     'addu $v1, $v1, $a0', 'sll $v1, $v1, 2', 'sw $ra, 0x10($sp)', 'addu $v1, $v0, $v1',
     'lw $v0, 0x68($v1)', 'bne $a1, $v0, 0x38', 'nop', 'j choose+0x48', 'lui $a1, 2',
     'lw $v0, 0x6c($v1)', 'bne $a1, $v0, 0x58', 'move $v0, $zero', 'lui $a1, 1',
     'jal call', 'nop', 'sll $v0, $v0, 0x18']
C = ['lui $v1, %hi(table)', 'lw $v1, %lo(table)($v1)', 'andi $a0, $a0, 0xff', 'sll $v0, $a0, 2',
     'addu $v0, $v0, $a0', 'sll $v0, $v0, 2']
ROWS = [('r', T[i], C[i] if i < len(C) else '') for i in range(len(T))]


def test_stages_base_and_returns_directly():
    result = variants(SOURCE, 'choose', '', ROWS)
    assert len(result) == 1
    assert '__repair_index_base = (void *)table;' in result[0][1]
    assert 'return call(idx, mode);' in result[0][1]
    assert 'goto done;' not in result[0][1]


def test_requires_measured_evidence_and_exclusive_locals():
    assert not variants(SOURCE, 'choose', '', [('r', x, x) for x in T])
    assert not variants(SOURCE.replace('0x6c', '0x70'), 'choose', '', ROWS)
    assert not variants(SOURCE.replace('extern s32', 'extern volatile s32'), 'choose', '', ROWS)
    assert not variants(SOURCE.replace('return result;', 'use(mode); return result;'), 'choose', '', ROWS)
