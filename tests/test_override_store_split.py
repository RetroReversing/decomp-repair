"""A local set to a constant, overwritten under a test and used once, written as an if/else with the use in each arm."""
from decomprepair import registry
from decomprepair.override_store_split import FAMILY, variants

SET_THEN_OVERRIDE = '''void f(void *arg0) {
    s32 var_v0;

    g();
    var_v0 = 4;
    if (M2C_FIELD(arg0, s32 *, 0x34) < 0) {
        var_v0 = -1;
    }
    M2C_FIELD(arg0, s32 *, 0x68) = var_v0;
}
'''


def test_the_store_after_the_join_goes_into_each_arm_in_both_orders_and_the_local_goes():
    # a 70-instruction N64 function: the local landed in $v1 where the target has $v0, 15 -> 0
    kids = variants(SET_THEN_OVERRIDE, 'f')
    assert [family for family, _ in kids] == [FAMILY, FAMILY]
    first, second = (text for _, text in kids)
    assert ('    if (M2C_FIELD(arg0, s32 *, 0x34) < 0) {\n        M2C_FIELD(arg0, s32 *, 0x68) = -1;\n'
            '    } else {\n        M2C_FIELD(arg0, s32 *, 0x68) = 4;\n    }\n}') in first
    assert ('    if (M2C_FIELD(arg0, s32 *, 0x34) >= 0) {\n        M2C_FIELD(arg0, s32 *, 0x68) = 4;\n'
            '    } else {\n        M2C_FIELD(arg0, s32 *, 0x68) = -1;\n    }\n}') in second
    assert 'var_v0' not in first and 'var_v0' not in second
    assert 'g();' in first


def test_the_if_else_spelling_gives_the_same_children():
    spelled = SET_THEN_OVERRIDE.replace('    var_v0 = 4;\n    if (M2C_FIELD(arg0, s32 *, 0x34) < 0) {\n        var_v0 = -1;\n    }',
                                        '    if (M2C_FIELD(arg0, s32 *, 0x34) < 0) {\n        var_v0 = -1;\n    } else {\n        var_v0 = 4;\n    }')
    assert spelled != SET_THEN_OVERRIDE
    assert variants(spelled, 'f') == variants(SET_THEN_OVERRIDE, 'f')


def test_a_return_a_call_argument_and_the_arm_s_own_statements_are_carried_along():
    source = '''s32 f(s32 a) {
    s32 r;

    r = 1;
    if (a > 3) {
        h(a);
        r = 2;
    }
    return r;
}
'''
    (_, text), _ = variants(source, 'f')
    assert 'if (a > 3) {\n        h(a);\n        return 2;\n    } else {\n        return 1;\n    }' in text
    call = source.replace('return r;', 'k(a, r);\n    return 0;')
    (_, text), _ = variants(call, 'f')
    assert 'k(a, 2);' in text and 'k(a, 1);' in text
    sum_ = source.replace('return r;', 'x = a - r;\n    return x;')
    (_, text), _ = variants(sum_, 'f')
    assert 'x = a - 2;' in text


def test_a_negative_value_inside_an_expression_is_parenthesised():
    source = SET_THEN_OVERRIDE.replace('M2C_FIELD(arg0, s32 *, 0x68) = var_v0;', 'M2C_FIELD(arg0, s32 *, 0x68) = 3 - var_v0;')
    (_, text), _ = variants(source, 'f')
    assert '= 3 - (-1);' in text and '= 3 - 4;' in text


def test_a_local_that_is_read_elsewhere_or_a_use_that_is_not_one_statement_is_left_alone():
    read_later = SET_THEN_OVERRIDE.replace('}\n', 'M2C_FIELD(arg0, s32 *, 0x6C) = var_v0;\n}\n')
    assert variants(read_later, 'f') == []
    used_before = SET_THEN_OVERRIDE.replace('    g();', '    g(var_v0);')
    assert variants(used_before, 'f') == []
    twice = SET_THEN_OVERRIDE.replace('= var_v0;', '= var_v0 + var_v0;')
    assert variants(twice, 'f') == []


def test_an_impure_test_or_value_is_left_alone():
    assert variants(SET_THEN_OVERRIDE.replace('M2C_FIELD(arg0, s32 *, 0x34) < 0', 'h() < 0'), 'f') == []
    assert variants(SET_THEN_OVERRIDE.replace('var_v0 = -1;', 'var_v0 = h();'), 'f') == []
    assert variants(SET_THEN_OVERRIDE.replace('var_v0 = 4;', 'var_v0 = i++;'), 'f') == []


def test_it_declares_itself():
    assert registry.get('override_store_split') is not None


def test_a_narrow_local_keeps_its_wrap_so_only_values_inside_its_range_are_folded():
    # `u8 v = -1` is 255: the folded literal would be read as -1
    narrow = SET_THEN_OVERRIDE.replace('s32 var_v0;', 'u8 var_v0;')
    assert variants(narrow, 'f') == []
    fits = narrow.replace('-1', '200')
    assert len(variants(fits, 'f')) == 2
    assert len(variants(SET_THEN_OVERRIDE.replace('s32 var_v0;', 's8 var_v0;'), 'f')) == 2
    assert len(variants(SET_THEN_OVERRIDE.replace('s32 var_v0;', 'void *var_v0;'), 'f')) == 2
