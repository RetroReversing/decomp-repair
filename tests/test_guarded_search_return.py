"""m2c's guarded `for (;;)` search with a duplicated exit return, written as the `while` that returns what it finds."""
from decomprepair import guarded_search_return as m
from decomprepair import registry

# The shape of a 13-instruction string search as m2c drafts it.
DRAFT = '''u8 *f(u8 *arg0, s32 arg1) {
    u8 *var_a0;

    var_a0 = arg0;
    if (*var_a0 != 0) {
        for (;;) {
            if (*var_a0 != arg1) {
                var_a0 += 1;
                if (*var_a0 == 0) {
                    /* Duplicate return node #6. Try simplifying control flow for better match */
                    return NULL;
                }
                continue;
            }
            break;
        }
        return var_a0;
    }
    return NULL;
}
'''

WANT = '''u8 *f(u8 *arg0, s32 arg1) {
    u8 *var_a0;

    var_a0 = arg0;
    while (*var_a0 != 0) {
        if (*var_a0 == arg1) {
            return var_a0;
        }
        var_a0 += 1;
    }
    return NULL;
}
'''


def test_the_search_becomes_a_while():
    assert m.variants(DRAFT, 'f') == [(m.FAMILY, WANT)]


def test_other_statements_stay_in_order():
    source = DRAFT.replace('var_a0 += 1;', 'var_a0 += 1;\n                count += 1;').replace(
        '        return var_a0;\n', '        found = 1;\n        return var_a0;\n')
    [(_, text)] = m.variants(source, 'f')
    assert 'found = 1;\n            return var_a0;\n        }\n        var_a0 += 1;\n        count += 1;\n    }' in text


def test_declines_when_the_program_would_change():
    for old, new in [('if (*var_a0 == 0) {', 'if (*var_a0 == 1) {'),
                     ('return NULL;\n                }', 'return arg0;\n                }'),
                     ('var_a0 += 1;\n', 'var_a0 += 1;\n                goto out;\n'),
                     ('        return var_a0;\n', '        var_a0 += 1;\n')]:
        assert old in DRAFT
        assert m.variants(DRAFT.replace(old, new), 'f') == []


def test_declares_itself():
    assert [entry.families for entry in registry.declared() if entry.module == 'guarded_search_return'] == [(m.FAMILY,)]
