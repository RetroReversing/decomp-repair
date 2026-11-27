"""A flag cleared before a guarded block that sets it last, written as the guard's `else` arm."""
from decomprepair import flag_default_else as p
from decomprepair import registry

SOURCE = '''void put(float a, float b)
{
    unsigned char done;

    done = 0;
    if (a != 1.0 && b != 1.0) {
        scale(a, b);
        done = 1;
    }
    if (done) {
        use(a);
    }
}
'''


def test_the_clear_becomes_the_else_arm():
    [(family, text)] = p.variants(SOURCE, 'put')
    assert family == p.FAMILY
    assert ('    if (a != 1.0 && b != 1.0) {\n        scale(a, b);\n        done = 1;\n    } else {\n'
            '        done = 0;\n    }\n    if (done) {') in text
    assert '    done = 0;\n    if' not in text


def test_not_when_the_guard_or_body_reads_the_flag_or_the_set_is_conditional():
    assert p.variants(SOURCE.replace('a != 1.0 &&', 'done != 1 &&'), 'put') == []
    assert p.variants(SOURCE.replace('scale(a, b);', 'scale(a, done);'), 'put') == []
    assert p.variants(SOURCE.replace('scale(a, b);', 'if (a)'), 'put') == []
    assert p.variants(SOURCE.replace('        done = 1;\n    }\n', '        done = 1;\n    } else {\n    }\n'), 'put') == []


def test_a_global_is_left_alone_and_it_is_registered():
    assert p.variants(SOURCE.replace('    unsigned char done;\n', ''), 'put') == []
    assert any(p.FAMILY in repair.families for repair in registry.declared())
