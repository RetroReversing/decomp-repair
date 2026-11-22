from decomprepair.measured_reset_loops import variants

SOURCE = '''
#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
void reset(void *base) {
    s32 saved;
    u32 first;
    u32 second;
    void *p;
    void *q;
    saved = M2C_FIELD(base, s32 *, 0);
    first = 0;
    p = base;
    do {
        M2C_FIELD(p, s16 *, 24) = 0;
        first += 1;
        p += 2;
    } while (first < 2U);
    second = 0;
    q = base;
    do {
        M2C_FIELD(q, s8 *, 6) = 0;
        second += 1;
        q = base + second;
    } while (second < 4U);
    clear(M2C_FIELD(base, s32 *, 16), saved);
}
'''
ROWS = [
    ('o', 'lw $a0, 0x10($s0)', ''),
    (' ', 'sb $zero, 6($v0)', 'sb $zero, 6($a0)'),
    ('o', '', 'lw $a0, 0x10($s0)'),
]


def test_stage_disjoint_field_and_reuse_counter():
    [(family, candidate)] = variants(SOURCE, 'reset', '', ROWS)
    assert family == 'measured_reset_loops'
    assert '__repair_reset_head = M2C_FIELD(base, s32 *, 16);' in candidate
    assert 'q = base + first;' in candidate
    assert 'while (first < 4U)' in candidate
    assert 'clear(__repair_reset_head, saved);' in candidate


def test_decline_unsafe_or_unsupported_shapes():
    for source, header, rows in [
        (SOURCE, '', []),
        (SOURCE.replace('void *base', 'volatile void *base'), '', ROWS),
        (SOURCE.replace('s16 *, 24', 's16 *, 16'), '', ROWS),
        (SOURCE.replace('s8 *, 6', 's8 *, 16'), '', ROWS),
        (SOURCE.replace('clear(M2C_FIELD', 'use(q); clear(M2C_FIELD'), '', ROWS),
        (SOURCE.replace('clear(M2C_FIELD', 'use(second); clear(M2C_FIELD'), '', ROWS),
        (SOURCE.replace('saved = M2C_FIELD', 'use(&base); saved = M2C_FIELD'), '', ROWS),
        (SOURCE, '#define clear(x,y) other(x,y)', ROWS),
        (SOURCE, 'typedef volatile int s32;', ROWS),
        (SOURCE.replace('(*(type_ptr)', '(effect(), *(type_ptr)'), '', ROWS),
    ]:
        assert variants(source, 'reset', header, rows) == []
