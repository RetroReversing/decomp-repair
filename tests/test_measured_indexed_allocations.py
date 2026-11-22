from decomprepair.measured_indexed_allocations import variants

SOURCE = '''void build(void) {
    u16 count;
    u32 index;
    void *allocated;
    void *base;
    void *cursor;
    base = (char *)&state + 128;
    clear(base, 0, 124);
    index = 0;
    parse(&first, &second);
    cursor = base;
    rows: {
        count = M2C_FIELD(base, u16 *, 62);
        if (count != 0) {
            allocated = allocate(1, count * 708);
            M2C_FIELD(cursor, void **, 84) = allocated;
            clear(allocated, 0, M2C_FIELD(base, u16 *, 62) * 708);
        }
        cursor += 4;
        index += 1;
        base += 2;
    }
    if (index < 10U) goto rows;
    parse(&first, &third);
    M2C_FIELD(&state, s32 *, 32) = 0;
    reset();
}'''
T = ['lhu $v0, 62($s0)', 'beql $v0, $zero, 172', 'addiu $s1, $s1, 4',
     'jal allocate', 'sw $v0, 84($s1)', 'jal clear', 'sltiu $v0, $s2, 10']
C = ['lhu $v0, 62($s0)', 'beqz $v0, 164']
ROWS = [('r', T[i], C[i] if i < len(C) else '') for i in range(len(T))]


def test_uses_one_index_for_both_strided_arrays():
    label, fixed = variants(SOURCE, 'build', '', ROWS)[0]
    assert label == 'measured_indexed_allocations'
    assert 'for (index = 0; index < 10U; index++)' in fixed
    assert 'M2C_FIELD((base + index * 2), u16 *, 62)' in fixed
    assert 'M2C_FIELD((base + index * 4), void **, 84)' in fixed
    assert fixed.count('M2C_FIELD((base + index * 2), u16 *, 62)') == 3


def test_requires_bounds_witness_and_unmodified_loop():
    assert not variants(SOURCE.replace('index < 10U', 'index < 65U'), 'build', '', ROWS)
    assert not variants(SOURCE.replace('cursor += 4;', 'touch(); cursor += 4;'), 'build', '', ROWS)
    assert not variants(SOURCE.replace('base += 2;', 'base += 4;'), 'build', '', ROWS)
    assert not variants(SOURCE, 'build', '#define index other', ROWS)
    assert not variants(SOURCE, 'build', '', [(' ', x, x) for x in T])
