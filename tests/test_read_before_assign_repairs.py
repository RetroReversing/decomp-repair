from decomprepair import read_before_assign_repairs as r

DRAFT = '''void f(void *arg0) {
    void *t;
    int *p;

    p = (int *)t + 4;
    *p = 1;
    t = *(void **)arg0;
    *(int *)t = 2;
}
'''


def test_moves_the_assignment_above_its_first_read():
    out = [t for _, t in r.variants(DRAFT, 'f')]
    assert any(t.index('t = *(void **)arg0;') < t.index('p = (int *)t + 4;') for t in out)
    assert all(t.count('t = *(void **)arg0;') == 1 for t in out)


def test_leaves_an_assignment_that_reads_a_value_changed_in_between():
    src = DRAFT.replace('t = *(void **)arg0;', 't = *(void **)p;')
    assert r.variants(src, 'f') == []


def test_leaves_a_local_assigned_before_it_is_read():
    src = '''void f(int a) {
    int t;

    t = a + 1;
    g(t);
}
'''
    assert r.variants(src, 'f') == []


def test_never_crosses_control_flow():
    src = '''void f(int a) {
    int t;

    g(t);
    if (a) return;
    t = a;
    g(t);
}
'''
    out = [t for _, t in r.variants(src, 'f')]
    assert out == []
