"""Calls to different functions put in the target's `jal` order."""
from decomprepair import registry
from decomprepair.jal_sequence_order import FAMILY, variants

SOURCE = '''void update(void *);
void draw(void *);

void func(char *a) {
    if (*(int *)(a + 0x44) < 0x15) {
        start(0x53);
    }
    update(a);
    update((*(void **)((char *)(a) + 0x48)));
    draw(a);
    draw((*(void **)((char *)(a) + 0x48)));
    *(int *)(a + 0x18) += 0x51;
}
'''
ASM = '''
    jal        start
    jal        update
    jal        draw
    jal        update
    jal        draw
'''
WANT = SOURCE.replace('''    update((*(void **)((char *)(a) + 0x48)));
    draw(a);
''', '''    draw(a);
    update((*(void **)((char *)(a) + 0x48)));
''')


def test_the_run_is_written_in_the_target_order():
    children = variants(SOURCE, 'func', ASM)
    assert children[0] == (FAMILY, WANT)


def test_nothing_when_the_order_is_already_the_targets():
    assert variants(WANT, 'func', ASM) == []


def test_calls_with_effects_in_their_arguments_stay():
    source = '''void func(int *p) {
    a(next());
    b(*p++);
}
'''
    assert variants(source, 'func', '    jal b\n    jal a\n    jal next\n') == []


def test_an_assigned_result_or_a_statement_between_ends_the_run():
    source = '''void func(int *p) {
    x = a(p);
    b(p);
    *p = 1;
    a(p);
}
'''
    assert variants(source, 'func', '    jal b\n    jal a\n    jal a\n') == []


def test_the_registry_runs_it():
    assert any(r.module == 'jal_sequence_order' for r in registry.declared())
