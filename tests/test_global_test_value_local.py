"""A tested-then-set global's old value held in a local of the test's own block."""
from decomprepair.global_test_value_local import variants

SOURCE = '''extern int busy, ready;
extern int idle;
void f(void)
{
    int started = 0;
    if (busy != 1) {
        started = 1;
    }
    busy = 1;
    if (ready == 0) {
        started = 2;
    }
    ready = 1;
    if (idle != 1) {
        started = 3;
    }
    idle = 1;
    g(started);
}
'''


def _squash(text):
    return ' '.join(text.split())


def test_the_first_latches_together_come_first_then_all_and_each():
    children = [_squash(text) for _, text in variants(SOURCE, 'f')]
    block = '{ int previous_value0 = busy; if (previous_value0 != 1) { started = 1; } } busy = 1;'
    assert block in children[0]
    assert 'int previous_value1 = ready; if (previous_value1 == 0)' in children[0]
    assert 'if (idle != 1)' in children[0]
    assert len(children) == 5
    assert all(f'previous_value{n}' in children[1] for n in range(3))
    assert block in children[2] and 'if (ready == 0)' in children[2]


def test_only_a_latch_of_a_declared_scalar():
    assert variants('extern int a; void f(void) { if (a != 1) { g(); } h(); a = 1; }', 'f') == []
    assert variants('extern int *a; void f(void) { if (a != 0) { g(); } a = 0; }', 'f') == []
    assert variants('void f(int a) { if (a != 1) { g(); } a = 1; }', 'f') == []
