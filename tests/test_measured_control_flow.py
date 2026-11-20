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
