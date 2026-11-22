from decomprepair.measured_list_key_search import variants

SOURCE = '''void *find(s32 key) {
    void *result;
    void *cursor;
    cursor = *M2C_FIELD(&state, void ***, 16);
    result = NULL;
    if (cursor != NULL) {
    loop:
        result = cursor;
        if (M2C_FIELD(cursor, s32 *, 12) != key) {
            cursor = M2C_FIELD(cursor, void **, 4);
            result = NULL;
            if (cursor != NULL) { goto loop; }
        }
    }
    return result;
}'''
T = ['lui $v0, %hi(head)', 'lw $v0, %lo(head)($v0)', 'lw $v1, ($v0)', 'beqz $v1, 44',
     'move $v0, $zero', 'lw $v0, 12($v1)', 'beq $v0, $a0, 44', 'move $v0, $v1',
     'lw $v1, 4($v1)', 'bnez $v1, 20', 'move $v0, $zero', 'jr $ra', 'nop']
ROWS = [('r', line, '') for line in T]
SYMBOLS = {'state': 100, 'head': 116}


def test_restores_direct_key_search():
    label, fixed = variants(SOURCE, 'find', '', ROWS, SYMBOLS.get)[0]
    assert label == 'measured_list_key_search'
    assert 'while (cursor != NULL)' in fixed
    assert 'M2C_FIELD(cursor, s32 *, 12) == key' in fixed
    assert 'return cursor;' in fixed
    assert 'return NULL;' in fixed


def test_requires_head_key_offsets_and_visible_control_flow():
    assert not variants(SOURCE, 'find', '', ROWS, None)
    assert not variants(SOURCE, 'find', '', ROWS, {'state': 100, 'head': 120}.get)
    assert not variants(SOURCE.replace('s32 *, 12', 's32 *, 16'), 'find', '', ROWS, SYMBOLS.get)
    assert not variants(SOURCE.replace('cursor = M2C_FIELD', 'touch(); cursor = M2C_FIELD'), 'find', '', ROWS, SYMBOLS.get)
    assert not variants(SOURCE, 'find', '#define cursor aliased', ROWS, SYMBOLS.get)
    assert not variants(SOURCE.replace('return result;', '/* retain */ return result;'), 'find', '', ROWS, SYMBOLS.get)
