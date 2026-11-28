from decomprepair.reorder_shared_label_cases import variants

SOURCE = '''void f(int op, int value) {
    switch (op) {
case 0x10: goto shared;
case 0x20: {
    if (value) work(); else { shared: other(); }
} break;
case 0x30: { third(); } break;
default: break;
    }
}
'''


def test_moves_cases_without_changing_the_shared_jump():
    children = variants(SOURCE, 'f')
    assert children
    assert any(t.index('case 0x30:') < t.index('case 0x20:') for _, t in children)
    assert all('goto shared;' in t and 'shared: other();' in t for _, t in children)


def test_rejects_fallthrough_external_jump_and_macros():
    assert not variants(SOURCE.replace('} break;\ndefault', '}\ndefault'), 'f')
    assert not variants(SOURCE.replace('    switch', '    if (value) goto shared;\n    switch'), 'f')
    assert not variants(SOURCE, 'f', '#define other() hidden()')
