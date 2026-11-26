"""A loop's counter that the function reuses elsewhere, given a fresh counter of its own in a block around the loop."""
from decomprepair.loop_counter_block_scope import FAMILY, assigned_first, variants

# The parts pass of a display-list interpreter (SN64 GCC 2.8.1): an empty inner loop counted with `k`, which the
# texture pass after it assigns afresh inside its `if` condition.
PASSES = '''void f(Part *parts, Tex *texs, s32 np, s32 nt)
{
    s32 i;
    s32 k;
    for (i = 0; i < np; i++) {
        parts[i].p = parts[i].p + 1;
        for (k = 0; k < parts[i].n; k++) {
        }
    }
    for (i = 0; i < nt; i++) {
        if ((k = texs[i].kind) <= 0) {
            texs[i].tex = k;
        }
    }
}
'''

WANT = '''        {
            s32 k_1;
            for (k_1 = 0; k_1 < parts[i].n; k_1++) {
            }
        }
'''


def _children(text):
    return [src for fam, src in variants(text, 'f') if fam == FAMILY]


def test_the_inner_counter_gets_a_block_of_its_own():
    kids = _children(PASSES)
    assert any(WANT in k and 'if ((k = texs[i].kind) <= 0)' in k for k in kids)


def test_a_counter_read_after_its_loop_is_left_alone():
    text = PASSES.replace('if ((k = texs[i].kind) <= 0)', 'if ((k += texs[i].kind) <= 0)')
    assert not any('k_1' in k for k in _children(text))


def test_a_conditional_reassignment_does_not_make_it_dead():
    text = PASSES.replace('if ((k = texs[i].kind) <= 0) {', 'if (nt && (k = texs[i].kind) <= 0) {')
    assert not any('k_1' in k for k in _children(text))
    text = PASSES.replace('    for (i = 0; i < nt; i++) {\n        if ((k', '    if (nt) {\n        k = 1;\n    }\n    t[0] = k;\n    for (i = 0; i < nt; i++) {\n        if ((k')
    assert not any('k_1' in k for k in _children(text))


def test_a_value_carried_round_an_enclosing_loop_is_left_alone():
    text = PASSES.replace('        parts[i].p = parts[i].p + 1;\n', '        parts[i].p = parts[i].p + k;\n')
    assert not any('k_1' in k for k in _children(text))


def test_a_counter_only_this_loop_names_is_not_renamed():
    text = PASSES.replace('if ((k = texs[i].kind) <= 0) {\n            texs[i].tex = k;', 'if (texs[i].kind <= 0) {\n            texs[i].tex = 0;')
    assert not any('k_1' in k for k in _children(text))


def test_goto_volatile_and_address_taken_decline():
    assert _children(PASSES.replace('    for (i = 0; i < nt', 'L:\n    for (i = 0; i < nt').replace('texs[i].tex = k;', 'texs[i].tex = k; goto L;')) == []
    assert _children(PASSES.replace('    s32 k;', '    volatile s32 k;')) == []
    assert not any('k_1' in k for k in _children(PASSES.replace('texs[i].tex = k;', 'texs[i].tex = k; g(&k);')))


def test_assigned_first():
    assert assigned_first(' if ((k = t->kind) <= 0) { k++; }', 'k')
    assert not assigned_first(' if (a || (k = t->kind) <= 0) {}', 'k')
    assert not assigned_first(' if (a) { k = 1; } x = k;', 'k')
    assert not assigned_first(' k = k + 1;', 'k')
    assert not assigned_first(' k == 1;', 'k')


def test_switch_arms_that_assign_first_keep_it_dead_and_one_that_reads_does_not():
    arms = ' switch (x) { case 1: k = 1; a = k; break; case 2: k = 2; break; }'
    assert assigned_first(arms, 'k')
    assert not assigned_first(arms.replace('case 2: k = 2;', 'case 2: a = k;'), 'k')
    assert not assigned_first(arms.replace('case 2: k = 2;', 'default: a = k;'), 'k')
