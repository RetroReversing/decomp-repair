from decomprepair.target_local_repairs import split_results

SOURCE = '''int f(void) {
    int value;
    value = find();
    observe(value);
    value = fallback();
    return value;
}'''


def test_call_result_split_keeps_exclusive_phase():
    assert any('observe(__repair_result_value);' in child and 'return value;' in child
               for _, child in split_results(SOURCE, 'f'))


def test_call_result_split_rejects_overwrite_that_a_path_bypasses():
    guarded = SOURCE.replace('value = fallback();', 'if (value == 0) {\n        value = fallback();\n    }')
    assert not split_results(guarded, 'f')
