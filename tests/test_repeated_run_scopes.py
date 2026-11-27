from decomprepair.repeated_run_scopes import FAMILY, variants

SOURCE = '''void f(int a) {
    int id;

    id = next_slot();
    if (id == 0xFFFF) {
        return;
    }
    spawn(id, a, 0x5B);
    id = next_slot();
    if (id == 0xFFFF) {
        return;
    }
    spawn(id, a, 0x5B);
}
'''


def test_every_copy_is_wrapped_in_one_child():
    (family, text), *_ = variants(SOURCE, 'f')
    assert family == FAMILY
    assert text.count('do {\nid = next_slot();') == 2
    assert text.count('} while (0);') == 2
    assert text.index('int id;') < text.index('do {')


def test_a_run_that_would_lose_its_break_is_left_alone():
    source = '''void f(int a) {
    int i;
    for (i = 0; i < a; i++) {
        step();
        if (i == 2) {
            break;
        }
        step();
    }
}
'''
    assert variants(source, 'f') == []


def test_a_call_made_once_gives_nothing():
    assert variants('void f(void) {\n    one();\n    two();\n}\n', 'f') == []
