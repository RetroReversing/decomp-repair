from decomprepair.measured_loop_search_target import variants

SOURCE = '''void *find(void *node) {
    u32 index;
    s32 step;
    index = 1;
    step = -1;
    if (node != NULL) {
loop_5:
        if (M2C_FIELD(node, s32 *, 8) != (index + step)) {
            node = M2C_FIELD(node, void **, 4);
            if (node != NULL) goto loop_5;
        }
    }
    return node;
}
'''
TARGET = ['beqz $v1, 0x74', 'nop', 'addu $a0, $a2, $a1', 'lw $v0, 0x6c($v1)',
          'lw $v0, 8($v0)', 'beq $v0, $a0, 0x74']
CANDIDATE = ['beqz $a0, 0x74', 'nop', 'lw $v0, 0x6c($a0)', 'lw $v1, 8($v0)',
             'addu $v0, $a2, $a1', 'beq $v1, $v0, 0x74']
ROWS = [('r', a, b) for a, b in zip(TARGET, CANDIDATE)]


def test_stages_sum_after_nonempty_guard():
    result = variants(SOURCE, 'find', '', ROWS)
    assert len(result) == 1
    assert 'u32 __repair_search_target;' in result[0][1]
    assert '__repair_search_target = index + step;\nloop_5:' in result[0][1]
    assert '!= __repair_search_target' in result[0][1]


def test_requires_evidence_and_unchanged_local_operands():
    assert not variants(SOURCE, 'find', '', [('r', a, a) for a in TARGET])
    assert not variants(SOURCE.replace('node = M2C_FIELD', 'index++; node = M2C_FIELD'), 'find', '', ROWS)
    assert not variants(SOURCE.replace('index = 1;', 'use(&index); index = 1;'), 'find', '', ROWS)
    assert not variants(SOURCE.replace('if (node != NULL)', 'if (node == NULL)', 1), 'find', '', ROWS)
