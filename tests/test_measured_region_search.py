from decomprepair.measured_region_search import variants

SOURCE = '''void *find(void *head, void *point) {
    s32 x;
    s32 y;
    void *cursor;
    void *result;
    cursor = head;
    x = M2C_FIELD(point, s32 *, 0);
loop:
    if ((x < M2C_FIELD(cursor, s32 *, 0x34)) || (M2C_FIELD(cursor, s32 *, 0x3C) < x) ||
        (y = M2C_FIELD(point, s32 *, 8), ((y < M2C_FIELD(cursor, s32 *, 0x44)) != 0)) ||
        (result = cursor, ((M2C_FIELD(cursor, s32 *, 0x48) < y) != 0))) {
        cursor = M2C_FIELD(cursor, void **, 0x5C);
        result = NULL;
        if (((s32) cursor != (s32) head) & (cursor != NULL)) { goto loop; }
    }
    return result;
}'''
T = ['lw $a3, ($a1)', 'lw $v0, 0x34($a2)', 'slt $v0, $a3, $v0',
     'lw $v0, 0x3c($a2)', 'lw $v0, 0x44($a2)', 'lw $v1, 8($a1)', 'slt $v0, $v1, $v0',
     'lw $v0, 0x48($a2)', 'lw $a2, 0x5c($a2)']
ROWS = [('r', x, '') for x in T]


def test_restores_ordered_bounds_and_search_loop():
    label, candidate = variants(SOURCE, 'find', '', ROWS)[0]
    assert label == 'measured_region_search'
    assert '__repair_y_min = M2C_FIELD(cursor, s32 *, 0x44);' in candidate
    assert candidate.index('__repair_y_min =') < candidate.index('y = M2C_FIELD(point, s32 *, 8);')
    assert 'return cursor;' in candidate
    assert 'while (cursor != head && cursor != NULL)' in candidate


def test_requires_measured_shape_and_no_extra_side_effects():
    assert not variants(SOURCE, 'find', '', ROWS[:-1])
    assert not variants(SOURCE.replace('result = NULL;', 'modify(cursor); result = NULL;'), 'find', '', ROWS)
    assert not variants(SOURCE.replace('s32 x;', 'volatile s32 x;'), 'find', '', ROWS)
    assert not variants(SOURCE.replace('return result;', '/* retain me */ return result;'), 'find', '', ROWS)
    assert not variants(SOURCE, 'find', '#define cursor elsewhere', ROWS)
