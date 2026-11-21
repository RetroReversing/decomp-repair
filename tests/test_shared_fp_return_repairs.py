from decomprepair.shared_fp_return_repairs import FAMILY, variants

SOURCE = """int f(int mode, float a, float b) {
    int flag;
    if (mode == 1) {
        flag = a < b;
        goto compare;
    }
    if (mode == 2) {
        flag = b < a;
        goto compare;
    }
    flag = a < 75.0f;
compare:
    return flag ? 1 : 0;
}
"""


def test_rewrites_every_comparison_and_preserves_predicates():
    [(family, text)] = variants(SOURCE, 'f')
    assert family == FAMILY
    assert 'goto compare' not in text
    for predicate in ('a < b', 'b < a', 'a < 75.0f'):
        assert f'if ({predicate}) goto __repair_fp_yes;' in text
    assert '__repair_fp_no: return 0;' in text


def test_rejects_unbraced_assignment_other_flag_uses_and_non_boolean_results():
    assert not variants(SOURCE.replace('flag = a < b;', 'if (mode) flag = a < b;'), 'f')
    assert not variants(SOURCE.replace('goto compare;', 'sink(&flag); goto compare;', 1), 'f')
    assert not variants(SOURCE.replace('a < b;', 'a < b ? 2L : 4294967296ULL;'), 'f')
    assert not variants(SOURCE, 'f', '#define flag alias')
