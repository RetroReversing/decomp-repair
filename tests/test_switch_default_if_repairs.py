"""m2c's default label inside a case arm's if, as the returns it came from."""
from decomprepair import switch_default_if_repairs as s

SOURCE = '''s32 f(s32 arg0) {
    s32 var_v0;

    switch (arg0) {
    case 2:
    case 3:
        var_v0 = 0;
        if (!((D != 1) & (D != 0x10))) {
        default:
            var_v0 = 1;
        }
        break;
    }
    return var_v0;
}
'''


def test_the_returns_it_came_from():
    # An N64 function at 36.6%: exact so.
    (family, out), = s.variants(SOURCE, 'f')
    assert family == 'switch_default_in_if'
    assert '''    case 3:
        if ((D != 1) & (D != 0x10)) {
            return 0;
        }
    default:
        return 1;
    }''' in out
    assert 'var_v0' not in out


def test_left_alone_when_the_variable_is_used_elsewhere():
    assert s.variants(SOURCE.replace('    return var_v0;', '    g(var_v0);\n    return var_v0;'), 'f') == []
    assert s.variants(SOURCE.replace('        break;\n', ''), 'f') == []
