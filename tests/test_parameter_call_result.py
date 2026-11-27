"""A call's result written back into the parameter it came from."""
from decomprepair.parameter_call_result import FAMILY, variants

DRAFT = '''s32 f(s32 arg0, s32 arg1)
{
    s32 var_s0;
    s32 var_s1;

    var_s0 = absS32(arg0);
    var_s1 = absS32(arg1);
    while (var_s0 > 0x100) {
        var_s0 >>= 1;
    }
    return var_s0 + var_s1;
}
'''


def _children(text):
    return [src for fam, src in variants(text, 'f') if fam == FAMILY]


def test_both_results_take_their_parameters_in_one_child_and_each_alone():
    children = _children(DRAFT)
    assert len(children) == 3
    assert children[0] == '''s32 f(s32 arg0, s32 arg1)
{

    arg0 = absS32(arg0);
    arg1 = absS32(arg1);
    while (arg0 > 0x100) {
        arg0 >>= 1;
    }
    return arg0 + arg1;
}
'''
    assert 'var_s1 = absS32(arg1);' in children[1]


def test_a_parameter_read_again_keeps_its_own_local():
    assert not _children('void f(s32 a) {\n    s32 v;\n    v = g(a);\n    h(v, a);\n}\n')


def test_a_call_in_a_loop_or_a_local_of_another_type_is_left_alone():
    assert not _children('void f(s32 a) {\n    s32 v;\n    while (h()) {\n        v = g(a);\n    }\n}\n')
    assert not _children('void f(s32 a) {\n    u8 v;\n    v = g(a);\n    h(v);\n}\n')
