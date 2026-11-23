"""A scalar global read as a loop bound after an array store: a one-member record (or array) read, the fence dropped."""
from decomprepair.loop_bound_record_read import FAMILY, REPAIR, variants

SAVED = '''extern s32 count;
extern int *rows[4][4];
void f(int i, int *q)
{
    s32 k;
    rows[0][i] = q;
    do { } while (0);
    for (k = 0; k < count; k++) {
        rows[k + 1][i] = q;
    }
}
'''


def _squash(text):
    return ' '.join(text.split())


def _children(source):
    return [_squash(src) for fam, src in variants(source, 'f') if fam == FAMILY]


def test_the_bound_is_read_through_a_record_and_the_fence_goes():
    first = _children(SAVED)[0]
    assert 'typedef struct { s32 n; } count_record; extern count_record count;' in first
    assert 'rows[0][i] = q; for (k = 0; k < count.n; k++)' in first


def test_the_fence_kept_and_the_array_form():
    children = _children(SAVED)
    assert any('do { } while (0); for (k = 0; k < count.n; k++)' in c for c in children)
    assert any('extern s32 count[];' in c and 'rows[0][i] = q; for (k = 0; k < count[0]; k++)' in c for c in children)


def test_no_child_when_the_global_is_written_or_declared_elsewhere():
    assert _children(SAVED.replace('rows[0][i] = q;', 'rows[0][i] = q; count = 2;')) == []
    assert _children(SAVED.replace('extern s32 count;\n', '')) == []


def test_it_declares_itself():
    assert REPAIR['families'] == (FAMILY,) and REPAIR['variants'] is variants
