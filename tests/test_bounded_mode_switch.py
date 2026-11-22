from decomprepair import range_case_switch_repairs as repair

SOURCE = '''
void f(void) {
    unsigned short state;
    state = get_mode();
    if (((state >= 0) && (state >= 2)) && (state < 4)) {
        if (ready()) {
            send(state);
        }
    }
    finish();
}
'''


def choices(source):
    return [text for family, text in repair.variants(source, 'f') if family == repair.BOUNDED_FAMILY]


def test_builds_small_switch_with_distinct_lower_defaults():
    [candidate] = choices(SOURCE)
    assert 'switch (state)' in candidate
    assert 'case 0: case 1: break;' in candidate
    assert 'case 2: case 3: {' in candidate
    assert 'default: break;' in candidate
    assert candidate.count('send(state);') == 1


def test_requires_local_unescaped_selector_and_exact_range():
    for source in (SOURCE.replace('unsigned short state;', 'volatile unsigned short state;'),
                   SOURCE.replace('state = get_mode();', 'state = get_mode();\n    escape(&state);'),
                   SOURCE.replace('state < 4', 'state <= 4'),
                   SOURCE.replace('(state >= 2)) && (state < 4)', '(state >= 2) && state) < 4')):
        assert not choices(source)


def test_skips_else_or_break_that_would_target_a_new_switch():
    assert not choices(SOURCE.replace('    finish();', '    else { recover(); }\n    finish();'))
    assert not choices(SOURCE.replace('            send(state);', '            break;'))
