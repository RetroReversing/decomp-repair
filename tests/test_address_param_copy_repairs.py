"""A parameter whose address a call took, read once into a local before its later uses."""
from decomprepair import address_param_copy_repairs as a

SOURCE = '''s32 f(s32 arg0, s32 arg1) {
    s32 temp_v0;

    temp_v0 = g(&arg0, arg1);
    if (temp_v0 == 0) {
        h(arg0);
        k();
        m(arg0);
    }
    return temp_v0;
}
'''


def test_one_copy_for_the_later_uses():
    # An N64 function at 91.2%: 96.3% with the copy, exact with target_call_arity after it.
    (family, out), = a.variants(SOURCE, 'f')
    assert family == 'address_param_copy'
    assert '    s32 __repair_arg0;\n' in out
    assert ('        __repair_arg0 = arg0;\n        h(__repair_arg0);\n        k();\n        m(__repair_arg0);\n') in out
    assert 'g(&arg0, arg1)' in out


def test_left_alone_otherwise():
    assert a.variants(SOURCE.replace('        m(arg0);\n', ''), 'f') == []  # one later use
    assert a.variants(SOURCE.replace('&arg0', 'arg0'), 'f') == []  # its address isn't taken
    assert a.variants(SOURCE.replace('        k();\n', '        arg0 = 1;\n'), 'f') == []  # assigned later
    assert a.variants(SOURCE.replace('        m(arg0);\n    }\n', '    }\n    m(arg0);\n'), 'f') == []  # two blocks
