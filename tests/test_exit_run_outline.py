from decomprepair import exit_run_outline as repair

GUARDED = """void f(Obj *o) {
    Obj *p;

    o->timer++;
    if (o->timer < 0x12D) {
        p = get(o);
        if (p == NULL) {
            o->x -= 1;
            return;
        }
        work(p);
    }
    o->state = 2;
}
"""

JUMPED = """void f(Obj *o) {
    Obj *p;

    if (o->timer < 0x12D) {
        p = get(o);
        if (p != NULL) {
            work(p);
            goto done;
        }
        o->x -= 1;
        o->y += 1;
        return;
    }
done:
    o->state = 2;
}
"""


def test_guard_body_moves_behind_the_end():
    (family, child), = repair.variants(GUARDED, 'f')
    assert family == 'exit_run_outline'
    assert 'if (p == NULL) {\n        goto repair_exit;' in child.replace('            goto', '        goto')
    assert child.rstrip().endswith('o->state = 2;\n    return;\nrepair_exit:\n    o->x -= 1;\n            return;\n}')


def test_run_after_the_jumping_if_moves_behind_the_end():
    children = [child for _, child in repair.variants(JUMPED, 'f')]
    child = children[-1]
    assert 'goto done;\n        }\n        goto repair_exit;\n    }' in child
    assert child.index('o->state = 2;') < child.index('repair_exit:') < child.index('o->y += 1;')


def test_nothing_when_no_code_follows():
    assert repair.variants('void f(int a) {\n    if (a) {\n        g();\n        return;\n    }\n}\n', 'f') == []


def test_nothing_when_the_run_reads_a_block_local():
    source = 'void f(int a) {\n    if (a) {\n        int b = g();\n        if (b) {\n            h(b);\n            return;\n        }\n    }\n    i();\n}\n'
    assert all('repair_exit:\n    int b' not in child and 'h(b);' not in child.split('repair_exit:')[1]
               for _, child in repair.variants(source, 'f'))


def test_value_function_needs_a_final_return():
    source = 'int f(int a) {\n    if (a) {\n        g();\n        return 1;\n    }\n    h();\n}\n'
    assert repair.variants(source, 'f') == []
