from decomprepair import range_case_switch_repairs as repair

SOURCE = """\
void f(int state) {
    int selected;
    selected = state;
    if (selected < 4) {
        if (selected < 2) {
            if (selected != 1) {
            } else {
                goto run;
            }
        } else {
            update();
        }
    } else if (selected == 4) {
    run:
        finish();
    }
}
"""


def candidates(source):
    return [candidate for family, candidate in repair.variants(source, 'f') if family == repair.JOINED_FAMILY]


def test_groups_range_and_joined_values_as_cases():
    first, second = candidates(SOURCE)
    assert 'switch (selected)' in first
    assert first.index('case 1:') < first.index('case 4:') < first.index('run:') < first.index('finish();')
    assert first.index('case 2:') < first.index('case 3:') < first.index('update();')
    assert first.index('finish();') < first.index('update();')
    assert second.index('update();') < second.index('finish();')
    assert first.count('finish();') == first.count('update();') == 1


def test_only_lower_endpoint_evaluates_duplicate_jump_condition():
    source = SOURCE.replace('goto run;', 'if (check()) { goto run; } else { goto run; }')
    for candidate in candidates(source):
        assert candidate.index('case 1:') < candidate.index('(void)(check());') < candidate.index('case 4:')
        assert candidate.count('check()') == 1


def test_rejects_volatile_selector_and_break_from_enclosing_loop():
    assert not candidates(SOURCE.replace('    int selected;', '    volatile int selected;'))
    assert not candidates(SOURCE.replace('update();', 'if (ready()) { break; }'))
