"""A guarded store outside every loop wrapped in a one-shot scope (a scroll window, 270 -> 205)."""
from decomprepair.store_guard_scope import FAMILY, variants

SOURCE = """void adjust(Window *w)
{
    s16 before;
    s32 i;

    for (i = 0; i < w->count; i++) {
        if (w->rows[i].y)
            w->scroll = 1;
    }
    if (!w->fixed)
        w->scroll = before;
    if (before < w->scroll)
        w->scroll = before;
    if (before - w->scroll >= w->limit) {
        w->scroll = before;
    } else
        w->scroll = 0;
}
"""


def children(source=SOURCE):
    return [text for family, text in variants(source, 'adjust') if family == FAMILY]


def test_each_plain_guarded_store_outside_a_loop_gets_one_child():
    found = children()
    assert len(found) == 2
    assert 'do {\n        if (!w->fixed)\n            w->scroll = before;\n    } while (0);' in found[0]
    assert 'do {\n        if (before < w->scroll)\n            w->scroll = before;\n    } while (0);' in found[1]


def test_a_store_inside_a_loop_is_left_to_statement_scope_weight():
    assert all('if (w->rows[i].y)\n            w->scroll = 1;' in text for text in children())


def test_an_if_with_an_else_or_a_break_is_not_wrapped():
    assert all('else\n        w->scroll = 0;' in text and 'if (before - w->scroll >= w->limit) {' in text for text in children())
    source = SOURCE.replace('        w->scroll = before;\n    if (before < w->scroll)', '        break;\n    if (before < w->scroll)')
    assert len(children(source)) == 1
