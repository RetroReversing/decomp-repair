"""m2c's two entries into one join become a retest of a copied pointer, and the delay loop a `for`."""
from decomprepair import guard_retest_join, registry

M2C = """void update(void *arg0) {
    u16 var_v1;
    void *temp_v0;

    temp_v0 = find(arg0);
    if (temp_v0 != NULL) {
        goto block_3;
    }
    if (arg0->timer < 0x65) {
        goto block_tail;
    }
    var_v1 = 0;
    goto block_6;
block_3:
    temp_v0->flag = 1;
    var_v1 = 0;
block_6:
    var_v1++;
    loop_goto_1:
    if (var_v1 < 3)
    {
        var_v1++;
        goto loop_goto_1;
    }
    reset(arg0);
    goto end;
block_tail:
    arg0->angle += 0x28;
end:
    return;
}
"""

STRUCTURED = """void update(Obj *self) {
    Obj *found;

    found = find(self);
    if (found != NULL || self->timer > 0x64) {
        if (found != NULL) {
            found->flag = 1;
        }
        reset(self);
    }
}
"""


def test_join_child_writes_the_retest_on_a_copy_and_the_delay_loop():
    children = guard_retest_join.variants(M2C, 'update')
    assert [family for family, _ in children] == ['skip_body_join_retest'] * 3
    first = children[0][1]
    assert 'void *temp_v0_copy;' in first
    assert 'temp_v0 = find(arg0);\n    temp_v0_copy = temp_v0;' in first
    assert 'if (temp_v0 != NULL || arg0->timer >= 0x65) {' in first
    assert 'if (temp_v0_copy != NULL) {\n            temp_v0->flag = 1;' in first
    assert 'for (var_v1 = 0; var_v1 < 3; var_v1++) {' in first
    assert '} else {\n        arg0->angle += 0x28;\n    }\n}\n' in first
    assert 'goto' not in first
    # without the loop, and without the copy
    assert 'loop_goto_1' in children[1][1] and 'temp_v0_copy' in children[1][1]
    assert 'temp_v0_copy' not in children[2][1]


def test_structured_retest_reads_a_copy():
    children = [child for family, child in guard_retest_join.variants(STRUCTURED, 'update') if family == 'guard_retest_copy']
    assert len(children) == 1
    assert 'Obj *found_copy;' in children[0]
    assert 'found_copy = found;' in children[0]
    assert 'if (found != NULL || self->timer > 0x64) {' in children[0]
    assert 'if (found_copy != NULL) {\n            found->flag = 1;' in children[0]


def test_counter_loop_and_unrelated_source():
    source = 'void wait(void) {\n    u16 i;\n    i = 0;\n    i++;\n    while (i < 5) {\n        i++;\n    }\n}\n'
    ((family, child),) = guard_retest_join.variants(source, 'wait')
    assert family == 'empty_counter_for' and 'for (i = 0; i < 5; i++) {\n    }' in child
    assert guard_retest_join.variants('void f(void) {\n    g();\n}\n', 'f') == []


def test_declared():
    (entry,) = [entry for entry in registry.declared() if entry.module.endswith('guard_retest_join')]
    assert registry.problems(entry) == []
