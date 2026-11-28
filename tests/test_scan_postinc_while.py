"""A guarded sentinel scan becomes `while (*p++ != 0)`, only where the pointer is not read afterwards."""
from decomprepair.scan_postinc_while import variants

DRAFT = '''s32 f(u8 *arg0) {
    s32 var_v1;
    u8 *var_a0;

    var_a0 = arg0;
    var_v1 = 0;
    if (*var_a0 != 0) {
        do {
            var_a0 += 1;
            var_v1 += 1;
        } while (*var_a0 != 0);
    }
    return var_v1;
}
'''


def test_a_guarded_scan_steps_in_its_condition():
    [(family, out)] = variants(DRAFT, 'f')
    assert family == 'scan_postinc_while'
    assert 'while (*var_a0++ != 0) {' in out
    assert 'var_a0 += 1' not in out
    assert 'do {' not in out and 'if (' not in out
    assert 'var_v1 += 1;' in out and 'return var_v1;' in out


def test_a_plain_while_with_only_the_step():
    source = 'void f(char *s) {\n    while (*s != 0) {\n        s++;\n    }\n}\n'
    [(_, out)] = variants(source, 'f')
    assert 'while (*s++ != 0) {\n    }' in out


def test_a_step_after_other_statements():
    source = 'void f(char *s) {\n    s32 n;\n    n = 0;\n    while (*s) {\n        n++;\n        ++s;\n    }\n    g(n);\n}\n'
    [(_, out)] = variants(source, 'f')
    assert 'while (*s++ != 0) {' in out and '++s;' not in out and 'n++;' in out


def test_declines_when_the_pointer_matters_later():
    after = DRAFT.replace('return var_v1;', 'return var_a0 - arg0;')
    assert variants(after, 'f') == []
    reads = DRAFT.replace('var_v1 += 1;', 'var_v1 += *var_a0;')
    assert variants(reads, 'f') == []
    other_bottom = DRAFT.replace('} while (*var_a0 != 0);', '} while (*var_a0 != 32);')
    assert variants(other_bottom, 'f') == []
    taken = DRAFT.replace('var_v1 = 0;', 'var_v1 = 0;\n    g(&var_a0);')
    assert variants(taken, 'f') == []
    outer = 'void f(char *s) {\n    do {\n        while (*s != 0) {\n            s++;\n        }\n    } while (g());\n}\n'
    assert variants(outer, 'f') == []
    braceless = 'void f(char *s, s32 a) {\n    while (a--)\n        while (*s != 0) {\n            s++;\n        }\n}\n'
    assert variants(braceless, 'f') == []
    global_pointer = 'void f(void) {\n    while (*gText != 0) {\n        gText++;\n    }\n}\n'
    assert variants(global_pointer, 'f') == []
    conditional = 'void f(char *s) {\n    while (*s != 0) {\n        if (g()) s++;\n    }\n}\n'
    assert variants(conditional, 'f') == []
    with_else = 'void f(char *s) {\n    if (*s != 0) {\n        do {\n            s++;\n        } while (*s != 0);\n    } else {\n        g();\n    }\n}\n'
    assert variants(with_else, 'f') == []
