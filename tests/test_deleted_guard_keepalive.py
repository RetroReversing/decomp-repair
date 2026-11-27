"""A loaded element stored from the identical arms of a guard that names the loop's pointers."""
from decomprepair import registry
from decomprepair.deleted_guard_keepalive import FAMILY, HOISTED, variants

SOURCE = '''u16 **poll(void) {
    s32 *flag;
    u16 **from;
    u16 *to;
    s32 i;

    i = 0;
    to = &copies;
    from = &sources;
    flag = &present;
    while (i < 4) {
        if (*flag != 0) {
            *to = **from;
            to += 1;
        } else {
            to += 1;
        }
        from += 1;
        i += 1;
        flag += 1;
    }
    return &sources;
}
'''


def test_the_tail_comes_out_and_the_store_moves_into_a_guard_naming_the_other_cursors():
    # the match needs both at once: the step written once alone scored worse (40 -> 70), the guard alone 50, together 0
    children = variants(SOURCE, 'poll')
    family, text = children[0]
    assert family == HOISTED
    assert '    u16 t_gk;\n' in text
    assert 't_gk = **from;\n            if (flag && from && *from) { *to = t_gk; } else { *to = t_gk; }' in text
    assert text.count('to += 1;') == 1
    assert text.count('{') == text.count('}')
    assert any(f == FAMILY and t.count('to += 1;') == 2 for f, t in children)
    assert any('if (*from) {' in t for _, t in children)


def test_a_store_outside_a_loop_or_through_no_pointer_local_is_left_alone():
    assert variants('void f(u16 **from) { u16 *to; to = &x; *to = **from; }', 'f') == []
    assert variants('void f(void) { int i; for (i = 0; i < 4; i++) { *gTo = **gFrom; } }', 'f') == []
    assert variants('void f(float **from) { float *to; while (*to) { *to = **from; to++; } }', 'f') == []


def test_the_registry_runs_it():
    assert any(entry.module.endswith('deleted_guard_keepalive') for entry in registry.declared())
