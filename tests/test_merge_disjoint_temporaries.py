"""One value per temporary, one after another, written as one variable set several times."""
from decomprepair.merge_disjoint_temporaries import FAMILY, variants

# m2c's shape: three temporaries of one saved register, a call after each, a fence around every call.
SAVED = '''s32 g(s32, s32);
void h(s32, s32);
void f(s32 arg0) {
    s32 temp_s0;
    s32 temp_s0_2;
    s32 temp_s0_3;
    do { temp_s0 = g(arg0, 1); } while (0);
    h(temp_s0, 2);
    do { temp_s0_2 = g(arg0, 3); } while (0);
    h(temp_s0_2, 4);
    do { temp_s0_3 = g(arg0, 5); } while (0);
    h(temp_s0_3, 6);
}
'''


def _squash(text):
    return ' '.join(text.split())


def _children(source=SAVED):
    return [_squash(text) for family, text in variants(source, 'f') if family == FAMILY]


def test_all_three_become_one_variable_declared_once():
    out = _children()
    merged = [s for s in out if 'temp_s0_2' not in s and 'temp_s0_3' not in s]
    assert merged
    one = next(s for s in merged if 'do {' in s)
    assert one.count('s32 temp_s0;') == 1
    assert 'h(temp_s0, 2); do { temp_s0 = g(arg0, 3); } while (0); h(temp_s0, 4); do { temp_s0 = g(arg0, 5);' in one


def test_the_fences_come_off_in_a_child_of_their_own():
    out = _children()
    bare = next(s for s in out if 'do {' not in s)
    assert 'temp_s0 = g(arg0, 1); h(temp_s0, 2); temp_s0 = g(arg0, 3); h(temp_s0, 4); temp_s0 = g(arg0, 5);' in bare


def test_each_neighbouring_pair_is_a_child():
    out = _children()
    assert any('temp_s0_3' in s and 'temp_s0_2' not in s for s in out)
    assert any('temp_s0_2' in s and 'temp_s0_3' not in s for s in out)


def _all_merged(out):
    return [s for s in out if 'temp_s0_2' not in s and 'temp_s0_3' not in s]


def test_a_use_after_the_next_assignment_is_left_alone():
    # the first temporary is read again after the third is set: no child merges the first with the third
    source = SAVED.replace('h(temp_s0_3, 6);', 'h(temp_s0_3, temp_s0);')
    out = _children(source)
    assert out and _all_merged(out) == []
    assert all('s32 temp_s0;' in s and 'temp_s0_2' in s and 'temp_s0_3' not in s for s in out)  # only _2 and _3 merge


def test_types_must_agree():
    out = _children(SAVED.replace('s32 temp_s0_2;', 's16 temp_s0_2;'))
    assert all('s16 temp_s0_2;' in s for s in out)  # the odd one out is never merged


def test_a_loop_holding_two_of_them_is_left_alone():
    source = '''s32 g(s32, s32);
void f(s32 n) {
    s32 temp_s0;
    s32 temp_s0_2;
    s32 i;
    for (i = 0; i < n; i++) {
        temp_s0 = g(i, 1);
        g(temp_s0, 2);
        temp_s0_2 = g(i, 3);
        g(temp_s0_2, 4);
    }
}
'''
    assert variants(source, 'f') == []


def test_a_backward_goto_counts_as_a_loop():
    source = '''s32 g(s32, s32);
void f(s32 n) {
    s32 temp_s0;
    s32 temp_s0_2;
top:
    temp_s0 = g(n, 1);
    g(temp_s0, 2);
    temp_s0_2 = g(n, 3);
    if (g(temp_s0_2, 4) != 0) goto top;
}
'''
    assert variants(source, 'f') == []


def test_an_address_taken_temporary_is_left_alone():
    out = _children(SAVED.replace('h(temp_s0_2, 4);', 'k(&temp_s0_2, 4);'))
    assert out and all('temp_s0_2' in s for s in out)  # only the other two merge


def test_a_temporary_read_before_it_is_set_is_left_alone():
    source = SAVED.replace('    do { temp_s0_2 = g(arg0, 3); } while (0);\n    h(temp_s0_2, 4);\n',
                           '    h(temp_s0_2, 4);\n    do { temp_s0_2 = g(arg0, 3); } while (0);\n')
    out = _children(source)
    assert out and all('temp_s0_2' in s for s in out)


def test_a_fence_around_a_jump_stays():
    source = SAVED.replace('do { temp_s0_2 = g(arg0, 3); } while (0);', 'do { temp_s0_2 = g(arg0, 3); goto out; } while (0);')
    out = _children(source)
    assert out and all('goto out; } while (0);' in s for s in out)
