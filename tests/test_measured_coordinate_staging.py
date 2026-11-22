from decomprepair import measured_coordinate_staging as repair

HEADER = '''typedef signed char s8; typedef signed short s16; typedef unsigned short u16;
typedef signed int s32; typedef unsigned int u32;'''
SOURCE = '''#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
extern s32 state;
void f(void *src, void *dst) {
    void *origin;
    u16 cy;
    s32 cx;
    s32 vy;
    s16 result;
    void *object;
    origin = M2C_FIELD(M2C_FIELD(&state, void **, 32), void **, 24);
    cy = M2C_FIELD(origin, u16 *, 14);
    cx = (s16) M2C_FIELD(origin, u16 *, 12) / 2;
    M2C_FIELD(dst, u16 *, 16) = (u16) (cx + ((s32) ((s16) (cx - M2C_FIELD(src, u16 *, 16)) * 25) >> 5));
    vy = (s32) ((s16) cy + ((u32) (cy << 16) >> 31)) >> 1;
    object = M2C_FIELD(dst, void **, 12);
    result = vy + ((s32) ((s16) (vy - M2C_FIELD(src, u16 *, 18)) * 25) >> 5);
    M2C_FIELD(dst, s16 *, 18) = result;
    consume(object, result);
}
'''
ROWS = [('r', op, '') for op in [
    'lw $a3, 24($t2)', 'lhu $v1, 16($a0)', 'lhu $v0, 12($a3)',
    'lhu $a0, 18($a0)', 'lhu $a3, 14($a3)',
    'lw $a3, 12($a1)', 'sra $v0, $v0, 5',
]]


def test_stages_source_coordinate_and_delays_object_read():
    (_, candidate), = repair.variants(SOURCE, 'f', HEADER, ROWS)
    assert 'int cy;' in candidate
    assert candidate.index('__repair_srcy = M2C_FIELD(src, u16 *, 18);') < candidate.index('M2C_FIELD(dst, u16 *, 16) =')
    assert candidate.index('result = vy +') < candidate.index('object = M2C_FIELD(dst, void **, 12);')
    assert 'consume(object, result);' in candidate


def test_does_not_reorder_unrelated_or_observable_operations():
    assert not repair.variants(SOURCE, 'f', HEADER, ROWS[:-1])
    assert not repair.variants(SOURCE.replace('object = M2C_FIELD', 'other(); object = M2C_FIELD'), 'f', HEADER, ROWS)
    assert not repair.variants(SOURCE.replace('consume(object, result);', 'consume(object, cy);'), 'f', HEADER, ROWS)
    assert not repair.variants(SOURCE.replace('u16 cy;', 'volatile u16 cy;'), 'f', HEADER, ROWS)
    assert not repair.variants(SOURCE, 'f', HEADER + '\n#define cy volatile_value', ROWS)
