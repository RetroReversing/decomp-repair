from decomprepair.measured_control_flow import variants


def test_shared_exit_flag_requires_zero_edge_and_single_merge():
    source = '''
void f(void *p) {
    int result;
    int work = 0;
    if (p) {
        if (check(p)) { result = 0; goto out; }
        work = 1;
    }
    result = work;
out:
    if (result == 0) finish(p);
}
'''
    rows = [(' ', 'bne $v1, $v0, out', 'bne $v1, $v0, out'),
            ('r', 'move $v0, $a1', 'move $v0, $zero')]
    assert variants(source, 'f', rows) == [
        ('measured_shared_exit_flag', source.replace('int result;', 'int result = 0;'))]
    assert not variants(source, 'f', rows[1:])
    assert not variants(source.replace('result = 0;', 'result = 1;'), 'f', rows)
    assert not variants(source.replace('check(p)', 'check(&result)'), 'f', rows)
    assert not variants(source.replace('int result;', 'static int result;'), 'f', rows)


def test_direct_count_result_preserves_the_empty_list_return():
    source = '''s32 f(void *head, s32 kind) {
    s32 count;
    s32 result;
    void *cursor;
    u16 value;
    count = 0;
    cursor = head;
    result = 0;
    if (cursor != NULL) {
        do {
            value = M2C_FIELD(cursor, u16 *, 8);
            cursor = M2C_FIELD(cursor, void **, 0);
            count += value == kind;
        } while (cursor != NULL);
        result = count;
    }
    return result;
}'''
    rows = [(' ', 'beqz $v1, 60', 'beqz $v1, 60'), ('r', 'move $v0, $a1', 'move $v0, $zero'),
            (' ', 'lhu $v0, 8($v1)', 'lhu $v0, 8($v1)')]
    fixed = dict(variants(source, 'f', rows))['measured_counted_list_result']
    assert 'return count;' in fixed and 'result' not in fixed
    assert not variants(source.replace('count = 0;', 'count = 1;'), 'f', rows)
    assert not variants(source.replace('result = count;', 'result = count + 1;'), 'f', rows)
