"""A global cursor read written after the unrelated store that follows it."""
from decomprepair import cursor_read_after_store as m
from decomprepair.registry import declared

SRC = '''extern void *gCursor;
void f(void *arg0, s32 a, s32 b) {
    void *p;
    void *q;
    s32 x;
    x = g(a);
    p = gCursor;
    gCursor = p + 8;
    ((S *) arg0)->value = (x & 15) << 4;
    *((s32 *) p + 0) = 1;
    q = gCursor;
    *((s32 *) arg0 + 2) = x;
    *((s32 *) q + 1) = 2;
}
'''


def kids(source=SRC):
    return [t for fam, t in m.variants(source, 'f') if fam == m.FAMILY]


def test_read_and_bump_move_past_the_store():
    first = kids()[0]
    assert first.index('->value') < first.index('p = gCursor;') < first.index('gCursor = p + 8;')
    assert 'q = gCursor;\n    *((s32 *) arg0 + 2)' in first


def test_plain_read_moves_and_all_sites_come_as_one_child():
    out = kids()
    assert len(out) == 3
    every = out[-1]
    assert every.index('(s32 *) arg0 + 2') < every.index('q = gCursor;')
    assert every.index('->value') < every.index('p = gCursor;')


def test_store_that_names_the_cursor_or_calls_is_left():
    bad = SRC.replace('->value = (x & 15) << 4', '->value = (x & 15) << (int) p')
    assert len(kids(bad)) == 1
    assert len(kids(SRC.replace('(x & 15) << 4;', 'h(x);'))) == 1


def test_a_local_or_undeclared_global_is_not_a_cursor():
    assert kids(SRC.replace('extern void *gCursor;\n', '')) == []


def test_a_block_closing_on_the_stores_line_stays_put():
    text = SRC.replace('    q = gCursor;\n', '    {\n    q = gCursor;\n').replace('*((s32 *) arg0 + 2) = x;', '*((s32 *) arg0 + 2) = x; }')
    last = kids(text)[-1]
    assert last.count('{') == last.count('}')
    assert 'q = gCursor; }' in last
    assert last.index('arg0 + 2') < last.index('q = gCursor;')


def test_it_declares_itself():
    assert any(r.module == 'cursor_read_after_store' for r in declared())
