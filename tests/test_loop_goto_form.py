"""A do-while loop with a call and a float literal, written as a backward goto."""
from decomprepair import loop_goto_form as t

SOURCE = '''void f(void)
{
    f32 x;
    s32 i;

    i = 0;
    x = 0.0f;
    do
    {
        g(x);
        x += 0.21f;
        i = i + 1;
    }
    while (i < 0x40U);
    h(x);
}
'''


def test_the_loop_becomes_a_backward_goto():
    # A 1133-instruction effect spawner: the sine-table loop's float literals, a double's address and the registers they
    # took were hoisted out of the do-while; as a goto loop they stay in the body (4035 -> 3555).
    out = [text for _, text in t.variants(SOURCE, 'f')]
    assert len(out) == 1
    assert 'loop_top:\n    {\n        g(x);' in out[0]
    assert '    }\n    if (i < 0x40U) goto loop_top;\n    h(x);' in out[0]
    assert 'do' not in out[0].replace('double', '')


def test_left_alone_otherwise():
    assert t.variants(SOURCE.replace('0.21f', '1'), 'f') == []  # no float literal
    assert t.variants(SOURCE.replace('g(x);', 'x += 1;'), 'f') == []  # no call
    assert t.variants(SOURCE.replace('i = i + 1;', 'if (x) break;'), 'f') == []  # a break
    assert t.variants(SOURCE.replace('g(x);', 's32 k = g(x);'), 'f') == []  # a declaration in the body


def test_it_declares_itself():
    from decomprepair import registry
    assert any(r.module == 'loop_goto_form' for r in registry.declared())
