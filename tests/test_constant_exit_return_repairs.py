"""A constant returned through the result's variable, returned directly where the tests fail."""
from decomprepair import constant_exit_return_repairs as c

SOURCE = '''s32 f(s32 arg0, s32 arg1) {
    s32 temp_s0;
    s32 temp_v0;
    s32 var_v0;

    temp_s0 = arg1 & 0xFF;
    if ((temp_s0 == 0xFF) || ((g(temp_s0) & 0xFF) == 0) || (temp_v0 = h(arg0 & 0x7F, temp_s0), var_v0 = temp_v0, (temp_v0 == -1))) {
        var_v0 = -1;
    }
    return var_v0;
}
'''


def test_returns_the_constant_and_the_value_it_was_copied_from():
    # An N64 function (gcc 2.7.2 -O2) at 96%: exact with the second form; the first alone was further off.
    (_, plain), (family, copied) = c.variants(SOURCE, 'f')
    assert family == 'constant_exit_return'
    assert '        return -1;\n    }\n    return var_v0;\n}' in plain and 'var_v0 = -1' not in plain
    assert 'var_v0' not in copied
    assert '(temp_v0 = h(arg0 & 0x7F, temp_s0), (temp_v0 == -1))) {\n        return -1;\n    }\n    return temp_v0;\n}' in copied


def test_keeps_the_variable_when_it_has_other_assignments():
    other = SOURCE.replace('    temp_s0 = arg1 & 0xFF;\n', '    var_v0 = 0;\n    temp_s0 = arg1 & 0xFF;\n')
    (_, plain), = c.variants(other, 'f')
    assert 'return -1;' in plain and 'return var_v0;' in plain


def test_left_alone_otherwise():
    def none(source):
        return c.variants(source, 'f') == []
    assert none(SOURCE.replace('var_v0 = -1;', 'var_v0 = arg0;'))  # not a constant
    assert none(SOURCE.replace('    return var_v0;', '    k();\n    return var_v0;'))  # not the last statement
    assert none(SOURCE.replace('    return var_v0;', '    return temp_s0;'))  # returns something else
    assert none(SOURCE.replace('    if ((temp_s0', '    while ((temp_s0'))  # a loop, not an if


def test_propose_finds_the_family():
    from decomprepair.propose import propose
    assert any(p.module == 'constant_exit_return_repairs' for p in propose(SOURCE, 'f').proposals)


def test_guard_and_cleanup_return_constants_directly():
    source = """\
s32 f(void *arg) {
    s32 result;
    global = arg;
    result = 0;
    if (arg != NULL) {
        if (ready) {
            notify();
        }
        result = 1;
        if (M2C_FIELD(arg, u8 *, 0xf) != 0) {
            cleanup(arg);
            result = 0;
        }
    }
    return result;
}
"""
    [(_, fixed)] = c.variants(source, 'f')
    assert 'if (arg == NULL) return 0;' in fixed
    assert 'if (M2C_FIELD(arg, u8 *, 0xf) == 0) return 1;\n        cleanup(arg);' in fixed
    assert fixed.count('return 0;') == 2
    assert not c.variants(source.replace('notify();', 'notify(&result);'), 'f')
    assert not c.variants(source.replace('cleanup(arg);', 'other(arg); cleanup(arg);'), 'f')
    assert not c.variants(source.replace('    result = 0;', '    if (ready)\n        result = 0;', 1), 'f')
