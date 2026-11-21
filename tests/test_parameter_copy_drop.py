from decomprepair.parameter_copy_drop_repairs import variants

SOURCE = """void walk(s32 arg0, void *arg1, s32 arg2, s32 arg3) {
    s32 var_s4;
    u32 count;
    var_s4 = arg2;
    count = 0;
    if (arg3 == 0) {
        var_s4 &= 0xFFFCFFFF;
    }
    call(arg1, 2, var_s4 | 0x1000, arg0);
}
"""


def test_the_local_copy_of_a_parameter_becomes_the_parameter():
    (family, candidate), = variants(SOURCE, 'walk')
    assert family == 'parameter_copy_drop'
    assert 'var_s4' not in candidate and 's32 var_s4;' not in candidate
    assert 'arg2 &= 0xFFFCFFFF;' in candidate and 'call(arg1, 2, arg2 | 0x1000, arg0);' in candidate
    assert 'arg2 = arg2' not in candidate and 'u32 count;' in candidate


def test_a_declaration_shared_with_other_locals_keeps_them():
    shared = SOURCE.replace('s32 var_s4;\n    u32 count;', 's32 var_s4, other;\n    u32 count;')
    (_, candidate), = variants(shared, 'walk')
    assert 's32 other;' in candidate and 'var_s4' not in candidate


def test_refused_when_the_copy_is_not_equivalent_to_the_parameter():
    assert not variants(SOURCE.replace('call(arg1', 'call(arg2, arg1'), 'walk')  # the parameter is read elsewhere
    assert not variants(SOURCE.replace('s32 var_s4;', 'u32 var_s4;'), 'walk')  # another type
    assert not variants(SOURCE.replace('call(arg1, 2, var_s4', 'call(&var_s4, 2, var_s4'), 'walk')
    late = SOURCE.replace('    var_s4 = arg2;\n', '    if (arg3) { var_s4 = 1; }\n    var_s4 = arg2;\n')
    assert not variants(late, 'walk')  # the local holds something before the copy
    nested = SOURCE.replace('    var_s4 = arg2;\n', '    if (arg3) { var_s4 = arg2; }\n')
    assert not variants(nested, 'walk')  # not at the top level


def test_the_last_parameter_can_be_the_one_copied():
    last = SOURCE.replace('var_s4 = arg2;', 'var_s4 = arg3;').replace('arg3 == 0', 'arg2 == 0')
    (_, candidate), = variants(last, 'walk')
    assert 'arg3 &= 0xFFFCFFFF;' in candidate and 'var_s4' not in candidate
