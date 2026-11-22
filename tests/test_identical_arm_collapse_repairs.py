from decomprepair import identical_arm_collapse_repairs as repair

SOURCE = '''void f(void *obj, void *held)
{
    if (held)
    {
        *((s32 *) (((char *) obj) + 0x60)) = 1;
        g();
    }
    else
    {
        *((s32 *) (((char *) obj) + 0x60)) = 1;
        g();
    }
    h();
}
'''


def test_equal_arms_are_written_once_where_the_if_stood():
    found = repair.variants(SOURCE, 'f')
    assert [family for family, _ in found] == ['identical_arm_collapse']
    text = found[0][1]
    assert 'if (' not in text and 'else' not in text
    assert text.count('g();') == 1
    assert '    *((s32 *) (((char *) obj) + 0x60)) = 1;\n    g();\n    h();' in text


def test_different_arms_and_conditions_with_effects_are_left_alone():
    assert not repair.variants(SOURCE.replace('= 1;\n        g();\n    }\n    h();', '= 2;\n        g();\n    }\n    h();'), 'f')
    assert not repair.variants(SOURCE.replace('if (held)', 'if (k())'), 'f')
    assert not repair.variants(SOURCE.replace('if (held)', 'if (held = x)'), 'f')


def test_an_if_that_is_the_unbraced_body_of_an_else_keeps_all_its_statements_in_that_arm():
    source = 'void f(int a, int b)\n{\n  if (a)\n  {\n    g(1);\n  }\n  else\n    if (b)\n  {\n    h(1);\n    h(2);\n  }\n  else\n  {\n    h(1);\n    h(2);\n  }\n}\n'
    texts = [text for _, text in repair.variants(source, 'f')]
    assert len(texts) == 1
    assert 'else\n    {\n      h(1);\n      h(2);\n    }' in texts[0].replace('else\n    ', 'else\n    ')
