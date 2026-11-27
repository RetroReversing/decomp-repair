"""A clamp written as an assignment inside the test is split, the narrow parameter copied to a local."""
from decomprepair import registry
from decomprepair.condition_assignment_param_local import FAMILIES, FAMILY, REPAIR, variants

SOURCE = """void clamp(s16 arg0, s16 arg2) {
    s32 var_a0;

    if (arg0 != -1) {
        if (arg2 < (var_a0 = (s32) (arg2 * 0x15E) / (s32) (arg0 + 1))) {
            var_a0 = (s32) arg2;
        }
        use(var_a0);
    }
}
"""


def kids(source=SOURCE):
    return [c for f, c in variants(source, 'clamp') if f == FAMILY]


def test_the_value_is_computed_first_and_the_parameter_is_copied_to_a_local():
    child = kids()[0]
    assert 's32 arg2c;' in child
    assert ('        var_a0 = (s32) (arg2 * 0x15E) / (s32) (arg0 + 1);\n        arg2c = (s32) arg2;\n'
            '        if (arg2c < var_a0) {\n            var_a0 = arg2c;\n        }\n        use(var_a0);') in child


def test_the_split_without_a_local_is_offered_too():
    assert any('if (arg2 < var_a0) {\n            var_a0 = arg2;' in c and 'arg2c' not in c for c in kids())


def test_another_arm_is_left_alone():
    assert not kids(SOURCE.replace('var_a0 = (s32) arg2;', 'var_a0 = 5;'))


def test_the_module_declares_itself():
    assert FAMILIES == (FAMILY,)
    assert REPAIR['families'] == FAMILIES
    assert registry.problems(registry.get('condition_assignment_param_local')) == []
