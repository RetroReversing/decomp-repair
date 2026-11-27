"""An `if` tree over one variable in the middle of a function, as a switch (ranges and `else if` included)."""
from decomprepair import embedded_if_tree_switch as t

SOURCE = '''void f(void)
{
    f32 width;
    f32 height;

    width = 160.0f;
    height = 120.0f;
    if (gMode != 0)
    {
        if (gCount != 2)
        {
            if (gCount >= 3)
            {
                if (gCount < 5)
                {
                    width = 80.0f;
                    height = 60.0f;
                }
            }
        }
        else
            if (gFlip == 1)
        {
            width = 80.0f;
        }
        else
        {
            height = 60.0f;
        }
    }
    draw(width, height);
}
'''


def test_the_range_tree_becomes_a_switch_with_the_single_value_first():
    # A 1133-instruction effect spawner: `switch (count)` laid the dispatch out as beq, slti, slti and the arm for 2
    # before the grouped arm for 3 and 4, where the nested ifs put the range arm first.
    out = [text for _, text in t.variants(SOURCE, 'f')]
    assert out and 'switch (gCount) {' in out[0]
    first = out[0]
    assert first.index('case 2:') < first.index('case 3:') < first.index('case 4:')
    assert 'if (gFlip == 1)' in first and 'height = 60.0f;' in first
    assert 'if (gCount' not in first
    assert 'draw(width, height);' in first and 'if (gMode != 0)' in first
    # the other order of the cases is a child too
    assert out[1].index('case 3:') < out[1].index('case 2:')


def test_one_test_is_an_if_not_a_switch():
    plain = 'void f(void)\n{\n    if (gMode != 0)\n    {\n        a();\n    }\n    else\n    {\n        b();\n    }\n}\n'
    assert t.variants(plain, 'f') == []


def test_left_alone_otherwise():
    assert t.variants(SOURCE.replace('width = 80.0f;\n                    height', 'return;\n                    height'),
                      'f') == []  # a return in the tree
    assert t.variants(SOURCE.replace('if (gCount < 5)', 'if (gOther < 5)'), 'f') == []  # two variables tested
    assert t.variants(SOURCE.replace('height = 60.0f;\n                }', 'gCount = 1;\n                }', 1),
                      'f') == []  # the variable changes in the tree
    assert t.variants(SOURCE.replace('if (gCount < 5)', 'if (gCount < 500)'), 'f') == []  # the range is too wide


def test_it_declares_itself_and_is_proposed():
    from decomprepair import registry
    assert any(r.module == 'embedded_if_tree_switch' for r in registry.declared())


GUARDED = '''void f(s32 i) {
    s32 a;
    s32 b;
    u16 state;

    state = table[i];
    if (state != 1) {
        if ((s32) state >= 2) {
            a = i & 0xFFFF;
            if (state != 2) {
                return;
            }
            g(a);
        } else {
            b = i & 0xFFFF;
            if (state != 0) {
                return;
            }
            h(b);
        }
    } else {
        k(i);
    }
}
'''


def test_leaves_that_return_early_in_a_void_function_are_cases():
    out = t.variants(GUARDED, 'f')[0][1]
    assert 'switch (state) {' in out and 'return' not in out
    assert out.index('case 0:') < out.index('h(b);') < out.index('case 1:') < out.index('k(i);') < out.index('case 2:')
    assert out.index('case 2:') < out.index('a = i & 0xFFFF;') < out.index('g(a);')


def test_early_returns_are_kept_when_code_follows_or_the_function_returns_a_value():
    assert t.variants(GUARDED.replace('        k(i);\n    }\n', '        k(i);\n    }\n    after();\n'), 'f') == []
    assert t.variants(GUARDED.replace('void f', 's32 f'), 'f') == []
    assert t.variants(GUARDED.replace('a = i & 0xFFFF;', 'count(i);'), 'f') == []
