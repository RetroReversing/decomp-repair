from decomprepair.global_pointer_local_repairs import measured_table_compare_pointer

SOURCE = """extern s32 table;
void f(int which, int row, int column) {
    s32 *entry;
    s32 previous;
    switch (which) {
    case 1:
        entry = &table;
        use(*entry);
        break;
    case 2:
        if (column) {
            previous = row;
            entry = &table;
            entry += row;
            entry += column;
            previous = column;
            if ((*entry) == previous) {
                done();
            }
        }
        break;
    }
}"""
ROWS = [
    ('r', 'lui $a0, %hi(table)', 'lui $a1, %hi(table)'),
    ('r', 'addiu $a0, $a0, %lo(table)', 'addiu $a1, $a1, %lo(table)'),
]


def test_split_only_guard_local_table_walk():
    [(label, candidate)] = measured_table_compare_pointer(SOURCE, 'f', ROWS)
    assert label == 'table_compare_pointer_scope'
    assert 'use(*entry);' in candidate
    assert 's32 *__repair_table_compare;' in candidate
    assert '(*__repair_table_compare) == previous' in candidate
    assert not measured_table_compare_pointer(SOURCE, 'f', ROWS[:1])
    assert not measured_table_compare_pointer(SOURCE.replace('done();', 'done(entry);'), 'f', ROWS)
    assert not measured_table_compare_pointer(SOURCE.replace('previous = row;', 'if (row)'), 'f', ROWS)
    assert not measured_table_compare_pointer(SOURCE.replace('switch (which)', 'while (row) switch (which)'), 'f', ROWS)

    no_prefix = SOURCE.replace('            previous = row;\n', '')
    assert 's32 *__repair_table_compare;\n            __repair_table_compare = &table;' in (
        measured_table_compare_pointer(no_prefix, 'f', ROWS)[0][1]
    )
