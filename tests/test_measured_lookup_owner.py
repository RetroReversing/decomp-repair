from decomprepair.measured_lookup_owner import variants

SOURCE = '''void *lookup(s32);
void sync(void *obj) {
    s32 neighbor;
    void *result;
    neighbor = M2C_FIELD(M2C_FIELD(obj, void **, 0xa8), s32 *, 0x24);
    if (neighbor != 0) {
        result = lookup(neighbor);
        if (result != NULL) {
            use(obj, M2C_FIELD(result, s32 *, 8));
        }
    }
}
'''
T = ['move $s0, $a0', 'lw $v0, 0xa8($s0)', 'lw $v0, 0x24($v0)', 'beqz $v0, 0x40', 'nop',
     'jal lookup', 'move $a1, $v0']
C = ['move $s0, $a0', 'lw $v0, 0xa8($s0)', 'lw $a0, 0x24($v0)', 'beqz $a0, 0x40', 'nop',
     'jal lookup', 'nop']
ROWS = [('r', a, b) for a, b in zip(T, C)]


def test_forwards_owner_and_reuses_pointer_result():
    result = variants(SOURCE, 'sync', '', ROWS)
    assert len(result) == 1
    assert 'void *lookup(void *, void *);' in result[0][1]
    assert 'neighbor = lookup(obj, neighbor);' in result[0][1]
    assert 'M2C_FIELD(neighbor, s32 *, 8)' in result[0][1]
    assert 'void *result;' not in result[0][1]


def test_requires_matching_call_and_exclusive_temporaries():
    assert not variants(SOURCE, 'sync', '', [('r', x, x) for x in T])
    assert not variants(SOURCE, 'sync', 'void *lookup(void *, void *);', ROWS)
    assert not variants(SOURCE.replace('neighbor = M2C_FIELD', 'use(neighbor); neighbor = M2C_FIELD'), 'sync', '', ROWS)
    assert not variants(SOURCE.replace('void *result;', 'volatile void *result;'), 'sync', '', ROWS)
