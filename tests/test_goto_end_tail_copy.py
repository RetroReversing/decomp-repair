"""goto_end_tail_copy: a run that ends a void function, written at each goto into it (a ladder of message draws)."""
from decomprepair import goto_end_tail_copy as family
from decomprepair import registry

LADDER = '''void f(s32 a) {
    u8 buf[0x100];
    s32 y;
    u8 *text;

    if (G == 0) {
        if (G2 == 1) {
            fmt(buf, &A);
            y = 0xC8;
            goto draw;
        }
        if (G2 == 2) {
            text = &B;
            goto print;
        }
        if (G2 == 3) {
            text = &C;
print:
            fmt(buf, text);
            y = 0xB4;
draw:
            show(buf, y, a);
        }
    }
}
'''

COPIED = '''void f(s32 a) {
    u8 buf[0x100];
    s32 y;
    u8 *text;

    if (G == 0) {
        if (G2 == 1) {
            fmt(buf, &A);
            y = 0xC8;
            show(buf, y, a);
            return;
        }
        if (G2 == 2) {
            text = &B;
            fmt(buf, text);
            y = 0xB4;
            show(buf, y, a);
            return;
        }
        if (G2 == 3) {
            text = &C;
            fmt(buf, text);
            y = 0xB4;
            show(buf, y, a);
        }
    }
}
'''


def test_every_run_is_copied_in_the_first_child():
    children = family.variants(LADDER, 'f')
    assert children[0] == ('goto_end_tail_copy', COPIED)
    assert len(children) == 2  # and the inner label alone; the outer run still holds that label


def test_an_unbraced_goto_takes_a_block():
    source = 'void f(int a) {\n    if (a) goto end;\n    g();\n    if (a > 1) {\nend:\n        h(a);\n    }\n}\n'
    out = family.variants(source, 'f')[0][1]
    assert 'if (a) { h(a); return; }' in out and 'end:' not in out


def test_a_run_something_follows_is_left_alone():
    source = 'void f(int a) {\n    if (a) { goto end; }\n    if (a > 1) {\nend:\n        h(a);\n    }\n    k();\n}\n'
    assert family.variants(source, 'f') == []


def test_a_run_in_a_loop_or_a_value_function_is_left_alone():
    loop = 'void f(int a) {\n    for (;;) {\n        if (a) { goto end; }\n        g();\nend:\n        h(a);\n    }\n}\n'
    value = 'int f(int a) {\n    if (a) { goto end; }\n    g();\nend:\n    h(a);\n}\n'
    assert family.variants(loop, 'f') == [] and family.variants(value, 'f') == []


def test_an_inner_declaration_of_a_used_name_declines():
    source = ('void f(int a) {\n    if (a) {\n        int b = 2;\n        g(b);\n        goto end;\n    }\n'
              'end:\n    h(b);\n}\n')
    assert family.variants(source, 'f') == []


def test_it_declares_itself():
    assert any(item.module == 'goto_end_tail_copy' for item in registry.declared())
