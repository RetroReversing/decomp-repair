from decomprepair import switch_tables

SOURCE = '''void f(int v) {
    int r;
    switch (v) {
    case 11:
        r = 1;
        break;
    case 12:
        r = 2;
        break;
    case 3:
    case 4:
    default:
        r = 3;
        break;
    }
    g(r);
}
'''


def test_every_label_is_rebuilt_from_the_table_in_arm_order():
    # Values 11.. : A at 11 and 14, B at 12 and 13, the rest (and the last entry) the default.
    table = (11, [0x100, 0x110, 0x110, 0x100, 0x200, 0x200, 0x200])
    found = [text for family, text in switch_tables.variants(SOURCE, 'f', [table]) if family == 'switch_table_labels']
    assert len(found) == 1
    assert 'case 11: case 14:\n        r = 1;' in found[0]
    assert 'case 12: case 13:\n        r = 2;' in found[0]
    assert 'case 17: default:\n        r = 3;' in found[0]


def test_declines_when_arms_and_destinations_do_not_pair():
    assert switch_tables.label_variants(SOURCE, 'f', [(11, [0x100, 0x110, 0x120, 0x200, 0x200])]) == []
    assert switch_tables.label_variants(SOURCE, 'f', []) == []
