from decomprepair import masked_copy_inline as copies

DRAFT = '''void f(void) {
    s32 var_v0;
    s32 var_v1;
    u16 var_a1;
    u32 temp_v0;

    var_a1 = head;
    var_v0 = var_a1 & 0xFFFF;
loop_1:
    var_v1 = var_a1 & 0xFFFF;
    if (flags[var_v0] == 2) {
        out[var_v1] = 0;
        var_v1 = var_a1 & 0xFFFF;
    }
    var_a1 = next[var_v1];
    temp_v0 = var_a1 & 0xFFFF;
    if (temp_v0 != 0xFFFF) {
        var_v0 = var_a1 & 0xFFFF;
        if (temp_v0 >= limit) {
            goto loop_1;
        }
    }
}
'''


def test_the_masked_copies_are_written_as_the_variable():
    [(family, out)] = copies.variants(DRAFT, 'f')
    assert family == 'masked_copy_inline'
    assert 'var_v0' not in out and 'var_v1' not in out and 'temp_v0' not in out
    assert 'flags[var_a1] == 2' in out and 'var_a1 = next[var_a1];' in out
    assert 'if (var_a1 != 0xFFFF) {' in out and 'if (var_a1 >= limit) {' in out


def test_each_narrow_variable_and_all_of_them():
    source = '''void f(u8 a, u16 b) {
    s32 x;
    int y;

    x = a & 0xFF;
    y = b & 0xFFFF;
    g(x, y);
}
'''
    out = [text for _, text in copies.variants(source, 'f')]
    assert len(out) == 3
    assert 'g(a, y);' in out[0] and 'g(x, b);' in out[1] and 'g(a, b);' in out[2]


def test_declines_copies_that_are_not_the_variable():
    # another width, another write, a stale read after the variable changed, an address taken, a narrow copy
    for body in ('x = a & 0xFFFF; g(x);', 'x = a & 0xFF; x += 1; g(x);', 'x = a & 0xFF; a = 2; g(x);',
                 'x = a & 0xFF; h(&x); g(x);', 'x = a & 0xFF; h(&a); g(x);'):
        assert copies.variants('void f(u8 a) {\n    s32 x;\n\n    ' + body + '\n}\n', 'f') == [], body
    assert copies.variants('void f(u8 a) {\n    u8 x;\n\n    x = a & 0xFF; g(x);\n}\n', 'f') == []
