from decomprepair import registry
from decomprepair.param_result_carrier_fold import FAMILY, variants

SOURCE = """s32 f(void *arg0, s32 arg1) {
    s32 var_s1;
    u32 temp_a0;

    var_s1 = 0;
    temp_a0 = arg1 & 0xFFFF;
    arg1 = 0 & 0xFF;
    if (temp_a0 >= 3) {
        if (temp_a0 > 9) {
            var_s1 = 1;
            g(arg0);
        }
        arg1 = var_s1 & 0xFF;
    }
    return arg1;
}
"""


def _kids(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_the_parameter_carrier_is_folded_into_the_flag_local():
    [kid] = _kids()
    assert 'return var_s1 & 0xFF;' in kid
    assert 'arg1 = 0 & 0xFF' not in kid and 'arg1 = var_s1' not in kid
    assert 'temp_a0 = arg1 & 0xFFFF;' in kid


def test_a_flag_changed_on_a_path_that_skips_the_copy_is_left():
    source = SOURCE.replace('        arg1 = var_s1 & 0xFF;\n    }', '    }\n    if (temp_a0 > 99) {\n        var_s1 = 2;\n    }\n    if (temp_a0 > 3) {\n        arg1 = var_s1 & 0xFF;\n    }')
    assert not _kids(source)


def test_a_parameter_read_after_the_carrier_starts_is_left():
    assert not _kids(SOURCE.replace('        arg1 = var_s1 & 0xFF;', '        g(arg1);\n        arg1 = var_s1 & 0xFF;'))


def test_the_module_is_registered():
    assert registry.problems(registry.get('param_result_carrier_fold')) == []
