from decomprepair import call_temp_load_reuse as module

SOURCE = """void f(u8 *p) {
    u32 t;
    s32 a;
    s32 b;
    u32 x;
    t = g(p);
    a = t & 0xFF;
    b = t & 0xFF00;
    h(a, b);
    x = p[0x48] & 4;
    if (x != 0)
    {
        h(x, a);
    }
}
"""


def test_reuses_the_call_temporary_for_the_load():
    kids = module.variants(SOURCE, 'f')
    assert [family for family, _ in kids] == ['call_temp_load_reuse']
    assert 't = p[0x48];\n    x = t & 4;' in kids[0][1]


def test_no_child_when_the_temporary_is_read_later():
    source = SOURCE.replace('h(x, a);', 'h(x, t);')
    assert module.variants(source, 'f') == []


def test_no_child_when_the_load_is_in_another_block():
    source = SOURCE.replace('    x = p[0x48] & 4;\n', '    {\n    x = p[0x48] & 4;\n    }\n')
    assert module.variants(source, 'f') == []
