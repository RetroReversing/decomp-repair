from decomprepair.reused_temp_split_repairs import guarded_scope_variants

SOURCE = '''
int f(int *p) {
    int value;
    if (p != 0) {
        value = *p;
        sink(value);
        value = p[1];
        sink(value);
    }
    return 0;
}
'''


def test_offers_split_and_guard_scope_together():
    result = guarded_scope_variants(SOURCE, 'f')
    assert any('do {\nif (p != 0)' in candidate and 'value_b1 = p[1];' in candidate
               and '} while (0);' in candidate for _, candidate in result)


def test_does_not_capture_an_else():
    source = SOURCE.replace('    return 0;', '    else { sink(0); }\n    return 0;')
    assert not guarded_scope_variants(source, 'f')


def test_does_not_change_break_or_continue_targets():
    assert not guarded_scope_variants(SOURCE.replace('sink(value);', 'break;', 1), 'f')
    assert not guarded_scope_variants(SOURCE.replace('sink(value);', 'continue;', 1), 'f')


def test_does_not_wrap_a_guard_entered_by_a_goto():
    source = SOURCE.replace('    if (p != 0)', '    goto label;\n    if (p != 0)').replace('value = *p;', 'label: value = *p;')
    assert not guarded_scope_variants(source, 'f')
