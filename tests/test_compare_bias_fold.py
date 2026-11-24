from decomprepair.compare_bias_fold import FAMILY, variants

SOURCE = '''void f(void *p)
{
    s32 t;
    if (((rand(0x64) + 1) <= 0x21U) || (t > 4))
    {
        use(p);
    }
    if ((get(p) + 2) < 10)
    {
        use(p);
    }
}
'''


def folded(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_a_biased_call_compared_with_a_literal_loses_its_bias():
    texts = folded()
    assert len(texts) == 3, 'each site, and both together'
    assert any('if ((rand(0x64) < 0x21U) || (t > 4))' in text and '(get(p) + 2) < 10' in text for text in texts)
    assert any('get(p) < 8)' in text for text in texts)


def test_a_bias_as_large_as_the_bound_or_an_expression_with_a_condition_is_left_alone():
    assert not folded(SOURCE.replace('+ 1) <= 0x21U', '+ 0x40) <= 0x21U').replace('+ 2) < 10', '+ 20) < 10'))
    assert not folded(SOURCE.replace('(rand(0x64) + 1)', '(a ? 1 : 2) + 1').replace('(get(p) + 2) < 10', 'x < 10'))


def test_a_parenthesised_bound_loses_the_bias_too():
    src = ('typedef unsigned short u16;\nvoid g(void);\nvoid f(int i, u16 *n)\n{\n'
           '  if ((i + 1) <= ((u16) n[2]))\n  {\n    g();\n  }\n}\n')
    texts = [t for _, t in variants(src, "f")]
    assert any('if (i < ((u16) n[2]))' in t for t in texts)
