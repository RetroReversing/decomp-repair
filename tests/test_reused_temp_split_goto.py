from decomprepair.reused_temp_split_repairs import FAMILY, variants

SOURCE = """
extern void sink(int);
void f(int mode) {
    int counter;
    counter = 0;
    if (mode) goto entered;
    counter = 0;
entered:
    do {
        sink(counter);
        counter++;
    } while (counter < 4);
}
"""


def test_split_does_not_bypass_counter_initialization_at_goto_target():
    assert variants(SOURCE, 'f') == []


def test_split_allows_jump_to_label_before_its_initialization():
    source = SOURCE.replace('    counter = 0;\nentered:', 'entered:\n    counter = 0;')
    assert any(family == FAMILY and 'sink(counter_b1);' in candidate
               for family, candidate in variants(source, 'f'))


def test_comment_does_not_supply_an_incoming_edge():
    source = SOURCE.replace('    if (mode) goto entered;', '    /* if (mode) goto entered; */')
    assert any(family == FAMILY for family, _ in variants(source, 'f'))


def test_split_does_not_read_undefined_value_after_branch_join():
    source = '''
void f(int mode, int input) {
    int value;
    value = 1;
    if (mode) {
        value = input;
    } else {
        value = 0;
    }
    sink(value);
}
'''
    assert not any('value_b2 = 0;' in candidate for _, candidate in variants(source, 'f'))


def test_split_does_not_leave_earlier_value_at_join():
    source = '''
void f(int mode, int input) {
    int value;
    value = 1;
    if (mode) {
        value = input;
        sink(value);
    }
    sink(value);
}
'''
    assert not any('value_b1 = input;' in candidate for _, candidate in variants(source, 'f'))


def test_split_allows_a_phase_confined_to_one_branch():
    source = '''
void f(int mode, int input) {
    int value;
    value = 1;
    sink(value);
    if (mode) {
        value = input;
        sink(value);
    }
}
'''
    assert any('value_b1 = input;' in candidate and 'sink(value_b1);' in candidate
               for _, candidate in variants(source, 'f'))
