"""The second pointer a draft copies a guarded call result into, written as the first one again."""
from decomprepair import registry
from decomprepair.guarded_copy_merge import FAMILY, REPAIR, variants

SOURCE = """void f(void *arg0) {
    void *p;
    void *q;

    p = spawn();
    if (p != NULL) {
        q = p;
        p = NULL;
        *(s32 *)((s8 *)q + 0x80) = 0x64;
        *(s32 *)((s8 *)q + 0x38) = 1;
    }
}
"""


def kids(source=SOURCE):
    return [child for _, child in variants(source, 'f')]


def test_the_copy_the_clear_and_the_second_local_go():
    assert kids() == ["""void f(void *arg0) {
    void *p;

    p = spawn();
    if (p != NULL) {
        *(s32 *)((s8 *)p + 0x80) = 0x64;
        *(s32 *)((s8 *)p + 0x38) = 1;
    }
}
"""]


def test_without_the_clear():
    assert len(kids(SOURCE.replace('        p = NULL;\n', ''))) == 1


def test_not_when_either_pointer_is_still_needed():
    assert kids(SOURCE.replace('0x38) = 1;', '0x38) = p != NULL;')) == []
    assert kids(SOURCE.replace('    }\n}', '    }\n    g(p);\n}')) == []
    assert kids(SOURCE.replace('    }\n}', '    }\n    g(q);\n}')) == []
    assert kids(SOURCE.replace('    void *q;', '    s32 *q;')) == []
    assert kids(SOURCE.replace('    p = spawn();', '    g(p);\n    p = spawn();')) == []
    assert kids(SOURCE.replace('    p = spawn();', '    p = spawn();\n  again:')) == []


def test_a_loop_or_goto_elsewhere_does_not_matter():
    assert len(kids(SOURCE.replace('    p = spawn();', '    do { g(); } while (0);\n    p = spawn();'))) == 1


def test_declared():
    assert REPAIR['families'] == (FAMILY,)
    assert registry.problems(registry.get('guarded_copy_merge')) == []
