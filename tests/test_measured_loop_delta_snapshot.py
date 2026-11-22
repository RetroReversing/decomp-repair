from decomprepair.measured_loop_delta_snapshot import variants

SOURCE = '''s32 sample(void *owner, u32 *out) {
    u32 value;
    u32 index;
    u32 minimum;
    void *cursor;
    minimum = -1U;
    if (M2C_FIELD(owner, u32 *, 4) == 0) { return 0; }
    index = 0;
    cursor = owner;
    rows: {
        if (((u32) M2C_FIELD(owner, u32 *, 4) >> index) & 1) {
            if (M2C_FIELD(owner, s32 *, 0x14) != 0) {
                M2C_FIELD(cursor, u32 *, 0xB8) = (u32) (M2C_FIELD(cursor, u32 *, 0xB8) - M2C_FIELD(owner, s32 *, 0x10));
            }
            value = M2C_FIELD(cursor, u32 *, 0xB8);
            if (value < minimum) { minimum = value; }
        }
        index += 1;
        cursor += 4;
    }
    if (index < 0x10U) goto rows;
    M2C_FIELD(owner, s32 *, 0x14) = 0;
    *out = minimum;
    return 1;
}'''
T = ['lw $v0, 4($a0)', 'lw $t1, 0x10($a0)', 'bnez $v0, 0x18', 'addiu $t0, $zero, -1',
     'lw $v0, 0xb8($a2)', 'subu $v0, $v0, $t1', 'sw $v0, 0xb8($a2)']
C = ['lw $v0, 4($a0)', 'bnez $v0, 0x14', 'addiu $t0, $zero, -1', 'lw $v0, 0xb8($a2)',
     'lw $v1, 0x10($a0)', 'subu $v0, $v0, $v1', 'sw $v0, 0xb8($a2)']
ROWS = [('r', a, b) for a, b in zip(T, C)]


def test_snapshots_delta_before_guard():
    result = variants(SOURCE, 'sample', '', ROWS)
    assert len(result) == 1
    candidate = result[0][1]
    assert candidate.index('__repair_delta_snapshot = M2C_FIELD(owner, s32 *, 0x10);') < candidate.index('minimum = -1U;')
    assert '- __repair_delta_snapshot)' in candidate


def test_requires_evidence_and_stable_disjoint_memory():
    assert not variants(SOURCE, 'sample', '', [('r', x, x) for x in T])
    assert not variants(SOURCE.replace('cursor += 4;', 'cursor += 4; modify(owner);'), 'sample', '', ROWS)
    assert not variants(SOURCE.replace('index < 0x10U', 'index < 0x100U'), 'sample', '', ROWS)
    assert not variants(SOURCE.replace('void *owner', 'volatile void *owner'), 'sample', '', ROWS)
    assert not variants(SOURCE, 'sample', '#define index global_index', ROWS)
    assert not variants(SOURCE.replace('0xB8', '0x10'), 'sample', '', ROWS)
