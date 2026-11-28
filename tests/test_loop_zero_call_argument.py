from decomprepair.loop_zero_call_argument import variants

SOURCE = '''void f(int n) {
    s32 i;
    for (i = 0; i < n; i++) {
        if (ready()) { call(1, 2, 3, 4, 5, 6, 7, 0x17, 9, 10); return; }
        call(1, 2, 3, 4, 5, 6, 7, 0x17, 9, 10);
    }
}
'''


def test_uses_initialized_index_in_both_calls():
    children = variants(SOURCE, 'f')
    assert any(text.count('0x17 | (i & ~i)') == 2 for _, text in children)


def test_rejects_incoming_jump_index_escape_write_and_macro():
    assert not variants(SOURCE.replace('for (i = 0;', 'goto inside; for (i = 0;').replace('if (ready())', 'inside: if (ready())'), 'f')
    assert not variants(SOURCE.replace('if (ready())', 'save(&i); if (ready())'), 'f')
    assert not variants(SOURCE.replace('if (ready())', 'i++; if (ready())'), 'f')
    assert not variants(SOURCE, 'f', '#define MUTATE() (i++)')
    assert not variants(SOURCE, 'f', '#define LINE __LINE__')
    assert not variants(SOURCE.replace('for (i = 0;', 'goto inside; for (i = 0;').replace('if (ready())', 'work(); inside: if (ready())'), 'f')
    assert not variants(SOURCE.replace('call(1, 2, 3, 4, 5, 6, 7, 0x17, 9, 10);\n', 'other(1, 2, 3, 4, 5, 6, 7, 0x17, 9, 10);\n'), 'f')
