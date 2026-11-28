"""A field read at the top of an `if` body, assigned inside the condition's last test."""
from decomprepair.condition_last_read_assign import variants

SOURCE = '''void f(Item *item, int ready)
{
    int kind;
    kind = item->kind;
    if (kind > 0 && (item->kind != 7 || item->count < 2)) {
        kind = item->kind;
        g(kind);
    }
}
'''


def test_the_read_moves_into_the_last_test():
    [(family, text)] = variants(SOURCE, 'f')
    assert family == 'condition_last_read_assign'
    assert 'if (kind > 0 && ((kind = item->kind) != 7 || item->count < 2)) {' in text
    assert text.count('kind = item->kind') == 2


def test_it_stays_where_it_would_change_what_runs():
    assert variants(SOURCE.replace('(item->kind != 7 || item->count < 2)', 'item->kind != 7 || ready'), 'f') == []
    assert variants(SOURCE.replace('item->kind != 7 ||', 'item->count < 2 ||'), 'f') == []
    assert variants(SOURCE.replace('        g(kind);\n    }', '        g(kind);\n    }\n    h(kind);'), 'f') == []
    assert variants(SOURCE.replace('item->count < 2', 'item->count < kind'), 'f') == []
