from decomprepair.measured_two_list_allocation import variants

SOURCE = '''M2C_UNK unlink_item(void *, void **);
M2C_UNK link_item(void *, void *);
extern void *pool;
s32 allocate(void **out, s16 priority) {
    s16 p;
    s32 selected;
    s32 result;
    void *entry;
    void *scan;
    p = priority;
    entry = M2C_FIELD(pool, void **, 0x20);
    selected = 0;
    if ((entry != NULL) || (entry = M2C_FIELD(pool, void **, 0x10), (entry != NULL))) {
        unlink_item(entry, out);
        *out = entry;
        link_item(entry, pool + 0x18);
        return 0;
    }
    scan = M2C_FIELD(pool, void **, 0x18);
    result = 0;
    if (scan != NULL) {
        do {
            if (p >= M2C_FIELD(scan, s16 *, 0x16)) {
                *out = scan;
                selected = 1;
            }
            scan = M2C_FIELD(scan, void **, 0);
            result = selected;
        } while (scan != NULL);
    }
    return result;
}
'''
T = ['lw $s0, 0x20($v0)', 'move $a2, $a0', 'bnez $s0, 0x34', 'move $s1, $zero',
     'lw $s0, 0x10($v0)', 'beqz $s0, 0x5c', 'nop', 'move $a0, $s0', 'jal unlink_item',
     'sw $s0, ($a2)', 'lui $a1, %hi(pool)', 'lw $a1, %lo(pool)($a1)', 'move $a0, $s0',
     'jal link_item', 'addiu $a1, $a1, 0x18', 'j allocate+0xac', 'move $v0, $s1']
C = ['lw $s0, 0x20($v0)', 'move $s1, $a0', 'bnez $s0, 0x34', 'move $a2, $zero',
     'lw $s0, 0x10($v0)', 'beqz $s0, 0x60', 'nop', 'move $a0, $s0', 'jal unlink_item',
     'move $a1, $s1', 'sw $s0, ($s1)']
ROWS = [('r', T[i] if i < len(T) else '', C[i] if i < len(C) else '') for i in range(len(T))]


def test_restores_shared_cursor_and_single_argument_unlink():
    result = variants(SOURCE, 'allocate', '', ROWS)
    assert len(result) == 1
    fixed = result[0][1]
    assert 'M2C_UNK unlink_item(void *);' in fixed
    assert '*out = entry;\n        unlink_item(entry);' in fixed
    assert 'void *scan;' not in fixed
    assert 'return selected;' in fixed


def test_rejects_conflicting_signature_and_extra_scalar_writes():
    assert not variants(SOURCE, 'allocate', '', [('r', x, x) for x in T])
    assert not variants(SOURCE, 'allocate', 'void unlink_item(void *);', ROWS)
    assert not variants(SOURCE.replace('selected = 1;', 'selected = 2;'), 'allocate', '', ROWS)
    assert not variants(SOURCE.replace('void *scan;', 'volatile void *scan;'), 'allocate', '', ROWS)
