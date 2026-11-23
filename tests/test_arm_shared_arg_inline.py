import re

from decomprepair.arm_shared_arg_inline import FAMILY, REPAIR, variants

SOURCE = """void menu(void)
{
    void *row;
    void *col;
    void *a;
    void *b;
    row = findRow(&gTable, 0x5B);
    col = findRow(&gTable, 0x5C);
    a = row - 0x28;
    if (gMode) {
        pickLabels(a, row, col - 0x28, 0x16C, 1);
    } else {
        placeLabels(a, row, col - 0x28, 1, 0xD);
    }
    b = col - 0x28;
    if (gCount == 2) {
        pickLabels(b, col, row, 0x66, 1);
    } else {
        placeLabels(b, col, row, 1, 0xD);
    }
}
"""


def _flat(text):
    return re.sub(r'\s+', ' ', text)


def _found(source=SOURCE, name='menu'):
    return [_flat(text) for family, text in variants(source, name) if family == FAMILY]


def test_each_shared_local_is_written_inline_in_both_arms():
    found = _found()
    first = [t for t in found if 'pickLabels(row - 0x28, row, col - 0x28' in t and 'b = col - 0x28' in t]
    assert first, found
    out = first[0]
    assert 'a = row - 0x28;' not in out and 'void *a;' not in out
    assert 'placeLabels(row - 0x28, row, col - 0x28, 1, 0xD)' in out


def test_all_of_them_come_as_one_child_too():
    found = _found()
    both = [t for t in found if 'a = row' not in t and 'b = col' not in t]
    assert both, found
    assert 'pickLabels(col - 0x28, col, row, 0x66, 1)' in both[0]
    assert 'placeLabels(col - 0x28, col, row, 1, 0xD)' in both[0]
    assert 'void *a;' not in both[0] and 'void *b;' not in both[0]


def test_nothing_when_a_later_statement_reads_it():
    later = SOURCE.replace('    b = col', '    use(a);\n    b = col', 1)
    assert not any('pickLabels(row - 0x28, row, col - 0x28' in t and 'use(a)' in t for t in _found(later))


def test_nothing_when_only_one_arm_reads_it_or_the_condition_does():
    one_arm = SOURCE.replace('placeLabels(a, row, col - 0x28, 1, 0xD)', 'placeLabels(row, row, col - 0x28, 1, 0xD)')
    assert not any('a = row' not in t and 'pickLabels(row - 0x28, row, col - 0x28' in t for t in _found(one_arm))
    cond = SOURCE.replace('if (gMode) {', 'if (a == gMode) {', 1)
    assert not any('pickLabels(row - 0x28, row, col - 0x28' in t for t in _found(cond))


def test_nothing_when_the_expression_reads_memory_or_an_input_changes_first():
    memory = SOURCE.replace('a = row - 0x28;', 'a = gBase[row];')
    assert not any('void *a;' not in t and 'pickLabels(gBase' in t for t in _found(memory))
    changed = SOURCE.replace('        pickLabels(a, row, col - 0x28, 0x16C, 1);', '        row = col;\n        pickLabels(a, row, col - 0x28, 0x16C, 1);')
    assert not any('pickLabels(row - 0x28' in t and 'row = col' in t for t in _found(changed))


def test_a_narrow_local_is_not_inlined():
    narrow = SOURCE.replace('void *a;', 'u8 a;')
    assert not any('void *a;' not in t and 'u8 a;' not in t and 'pickLabels(row - 0x28, row' in t and 'b = col' in t
                   for t in _found(narrow))


def test_it_declares_itself_for_every_lane():
    assert REPAIR['variants'] is variants and REPAIR['needs'] == ('source', 'name')
