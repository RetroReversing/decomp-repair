from decomprepair import registry
from decomprepair.result_local_reuse import FAMILY, variants

SOURCE = """void f(void *p) {
    s32 temp_a1;
    s32 temp_v0;
    s32 var_a0;
    s32 sum;

    sum = 0;
    while (p != NULL) {
        temp_v0 = g(p);
        temp_a1 = h(p);
        if (temp_v0 == 0) {
            var_a0 = 0x64;
        } else {
            var_a0 = (s32) (temp_a1 * 0x4650) / temp_v0;
        }
        if (temp_a1 < var_a0) {
            var_a0 = temp_a1;
        }
        sum += var_a0;
        p = next(p);
    }
}
"""


def _kids(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_the_computed_value_is_written_back_into_the_call_result():
    [kid] = _kids()
    assert 'temp_v0 = 0x64;' in kid
    assert 'temp_v0 = (s32) (temp_a1 * 0x4650) / temp_v0;' in kid
    assert 'if (temp_a1 < temp_v0) {' in kid and 'sum += temp_v0;' in kid
    assert 's32 var_a0;' in kid


def test_a_result_read_after_the_branch_keeps_its_own_local():
    assert not _kids(SOURCE.replace('sum += var_a0;', 'sum += var_a0 + temp_v0;'))


def test_a_value_used_before_the_branch_is_left():
    assert not _kids(SOURCE.replace('        temp_a1 = h(p);', '        temp_a1 = h(p);\n        var_a0 = 1;'))


def test_the_module_is_registered():
    assert registry.problems(registry.get('result_local_reuse')) == []
