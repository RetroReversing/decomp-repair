"""A guarded byte-cursor fill loop written as an indexed `for` loop; a literal chain's targets exchanged."""
from decomprepair import byte_cursor_fill_loop, constant_chain_swap, registry

SOURCE = '''
extern u16 gCount;
extern void *gFirst;
extern void *gSecond;

void fill(void) {
    s16 *temp_v1;
    u32 var_a1;
    void *var_a0;
    void *var_a2;
    s16 *temp;

    var_a1 = 0;
    if ((*(s32 *)&gCount) != 0) {
        var_a2 = gFirst;
        var_a0 = gSecond;
        do {
            temp_v1 = var_a2 + 0x1000;
            *temp_v1 = 0xFFFF;
            var_a1 += 1;
            var_a2 += 8;
            temp = (s16 *)((s8 *)var_a0 + 0x1000);
            (*temp) = 0xFFFF;
            var_a0 += 8;
        } while (var_a1 < (u32) gCount);
    }
}
'''


def texts(source):
    return [text for _, text in byte_cursor_fill_loop.variants(source, 'fill')]


def test_cursors_become_indexed_for_loop_chained_in_stored_order_first():
    first = texts(SOURCE)[0]
    assert 'for (var_a1 = 0; var_a1 < (u32) (*(s32 *)&gCount); var_a1++) {' in first
    assert ('((u16 *) gSecond)[var_a1 * 4 + 0x800] = ((u16 *) gFirst)[var_a1 * 4 + 0x800] = 0xFFFF;') in first
    for gone in ('var_a0', 'var_a2', 'temp_v1', 'temp;', 'do {', 'if ('):
        assert gone not in first
    assert 'u32 var_a1;' in first


def test_offers_statements_both_chains_and_the_declared_bound():
    children = texts(SOURCE)
    assert len(children) == 6
    assert any('var_a1 < (u32) gCount;' in child for child in children)
    assert any('((u16 *) gFirst)[var_a1 * 4 + 0x800] = 0xFFFF;\n        ((u16 *) gSecond)' in c for c in children)


def test_field_spelling_and_store_after_the_step():
    source = '''
void fill(s32 count) {
    u32 i;
    void *p;

    i = 0;
    if (count > 0) {
        p = gFirst;
        do {
            i += 1;
            p += 4;
            M2C_FIELD(p, s16 *, 0x10) = 1;
        } while (i < (u32) count);
    }
}
'''
    child = texts(source)[0]
    assert '((s16 *) gFirst)[i * 2 + 0xa] = 1;' in child  # one step past the written offset


def test_declines_when_the_meaning_would_change():
    used_after = SOURCE.replace('        } while (var_a1 < (u32) gCount);\n    }\n',
                                '        } while (var_a1 < (u32) gCount);\n    }\n    use(var_a2);\n')
    with_else = SOURCE.replace('        } while (var_a1 < (u32) gCount);\n    }\n',
                               '        } while (var_a1 < (u32) gCount);\n    } else {\n        use();\n    }\n')
    with_call = SOURCE.replace('var_a1 += 1;', 'var_a1 += 1;\n            use();')
    other_guard = SOURCE.replace('(*(s32 *)&gCount) != 0', 'gOther != 0')
    signed = SOURCE.replace('u32 var_a1;', 's32 var_a1;').replace('(u32) gCount', 'gCount')
    uneven = SOURCE.replace('var_a2 += 8;', 'var_a2 += 3;')
    for source in (used_after, with_else, with_call, other_guard, signed, uneven):
        assert texts(source) == []


def test_chain_targets_exchanged():
    source = 'void f(void) {\n    a[i] = b->c[i] = 0xFFFF;\n    x = y == 0;\n}\n'
    [(family, child)] = constant_chain_swap.variants(source, 'f')
    assert family == 'constant_chain_swap'
    assert 'b->c[i] = a[i] = 0xFFFF;' in child and 'x = y == 0;' in child
    assert constant_chain_swap.variants('void f(void) {\n    a = a = 1;\n    *p++ = q = 1;\n}\n', 'f') == []


def test_both_declare_themselves():
    modules = {repair.module for repair in registry.declared()}
    assert {'byte_cursor_fill_loop', 'constant_chain_swap'} <= modules
