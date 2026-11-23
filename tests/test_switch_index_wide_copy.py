"""A narrow loop counter a switch dispatches on: an `s32` copy at the top of the body, its wrappers and the call's."""
from decomprepair.switch_index_wide_copy import FAMILY, REPAIR, variants

SAVED = '''void f(char *e)
{
    s16 j;
    s32 n;
    for (j = 0; j < 3; j++) {
        do { do { *(int *)(e + j * 4) = 0; } while (0); } while (0);
        if (g != 0) {
            if (j == 1) {
                continue;
            }
        }
        *(int *)(e + j * 4) = h(e[2]);
        if (*(int *)(e + j * 4) != 0) {
            switch (j) {
            case 0: k(j, "j"); break;
            case 1: k(1, "x"); break;
            }
        }
    }
}
'''


def _squash(text):
    return ' '.join(text.split())


def _children(source):
    return [_squash(src) for fam, src in variants(source, 'f') if fam == FAMILY]


def test_the_copy_renames_every_use_in_the_body_but_not_the_header():
    first = _children(SAVED)[0]
    assert 's16 j; s32 jj;' in first
    assert 'for (j = 0; j < 3; j++) { jj = j;' in first
    assert 'switch (jj)' in first and 'if (jj == 1)' in first and 'e + jj * 4' in first
    assert 'k(jj, "j")' in first


def test_the_measured_child_wraps_the_copy_moves_the_wrappers_and_wraps_the_call():
    children = _children(SAVED)
    assert any('do { jj = j; } while (0); *(int *)(e + jj * 4) = 0; if (g != 0)' in c
               and 'do { *(int *)(e + jj * 4) = h(e[2]); } while (0);' in c for c in children)
    assert any('do { jj = j; } while (0); do { do { *(int *)(e + jj * 4) = 0;' in c
               and 'do { *(int *)(e + jj * 4) = h(e[2]); } while (0);' in c for c in children)


def test_no_child_when_the_counter_is_wide_or_assigned_in_the_body():
    assert _children(SAVED.replace('s16 j;', 's32 j;')) == []
    assert _children(SAVED.replace('continue;', 'j = 2; continue;')) == []
    assert _children(SAVED.replace('switch (j)', 'switch (n)')) == []


def test_it_declares_itself():
    assert REPAIR['families'] == (FAMILY,) and REPAIR['variants'] is variants
