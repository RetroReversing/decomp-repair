from decomprepair.compare_tree_shared_label import variants

SOURCE = '''void f(int op, int value) {
    if (op != 0x20) {
        if (op < 0x21) {
            if (op != 0x10) { return; }
            goto shared;
        } else if (op != 0x30) { return; }
        else { do_three(); }
    } else {
        if (value) { do_two(); }
        else { shared: do_shared(); }
    }
}
'''


def test_retains_jump_into_other_case():
    text = variants(SOURCE, 'f')[0][1]
    assert 'switch (op)' in text
    assert 'goto shared;' in text and 'shared: do_shared();' in text
    assert 'case 0x10:' in text and 'case 0x20:' in text and 'case 0x30:' in text


def test_rejects_external_jump_and_code_after_tree():
    assert not variants(SOURCE.replace('if (op != 0x20)', 'if (value) goto shared; if (op != 0x20)'), 'f')
    assert not variants(SOURCE.replace('\n}', '\n    finish();\n}'), 'f')
    assert not variants(SOURCE, 'f', '#define do_shared() other()')
    assert not variants(SOURCE.replace('int op', 'unsigned int op'), 'f')
    assert not variants(SOURCE.replace('int op', 'volatile int op'), 'f')
    assert not variants(SOURCE.replace('op != 0x10', 'op != 0x10U'), 'f')
