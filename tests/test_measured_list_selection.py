from decomprepair.measured_list_selection import variants

SOURCE = '''
#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
s32 choose(void *pool, void **out) {
    s32 found;
    s32 result;
    void *free_node;
    void *node;
    free_node = M2C_FIELD(pool, void **, 20);
    found = 0;
    if (free_node != NULL) {
        *out = free_node;
        unlink(free_node);
        return 0;
    }
    node = M2C_FIELD(pool, void **, 12);
    result = 0;
    if (node != NULL) {
        do {
            if (M2C_FIELD(node, s32 *, 8) == 0) {
                *out = node;
                found = 1;
            }
            node = M2C_FIELD(node, void **, 0);
            result = found;
        } while (node != NULL);
    }
    return result;
}
'''
ROWS = [
    ('r', 'sw $s2, 24($sp)', 'sw $ra, 24($sp)'),
    ('r', 'move $s2, $zero', 'move $a3, $zero'),
    ('r', 'move $v0, $s2', 'move $v0, $zero'),
]


def test_join_branches_and_reuse_cursor():
    [(family, candidate)] = variants(SOURCE, 'choose', '', ROWS)
    assert family == 'measured_list_selection'
    assert '} else {' in candidate
    assert 'free_node = M2C_FIELD(pool, void **, 12);' in candidate
    assert 'return found;' in candidate
    assert 'result = found;' not in candidate


def test_decline_escaped_or_live_locals_and_unproven_shapes():
    for source, header, rows in [
        (SOURCE, '', []),
        (SOURCE.replace('s32 found;', 'volatile s32 found;'), '', ROWS),
        (SOURCE.replace('void *free_node;', 'static void *free_node;'), '', ROWS),
        (SOURCE.replace('void *free_node;', 'const void *free_node;'), '', ROWS),
        (SOURCE.replace('unlink(free_node);', 'use(&found); unlink(free_node);'), '', ROWS),
        (SOURCE.replace('unlink(free_node);', 'found = 1; unlink(free_node);'), '', ROWS),
        (SOURCE.replace('return 0;', 'return 1;'), '', ROWS),
        (SOURCE.replace('result = found;', 'use(result); result = found;'), '', ROWS),
        (SOURCE.replace('result = found;', 'break; result = found;'), '', ROWS),
        (SOURCE, '#define CAPTURE found', ROWS),
        (SOURCE, '#undef M2C_FIELD', ROWS),
    ]:
        assert variants(source, 'choose', header, rows) == []
