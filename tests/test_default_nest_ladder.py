from decomprepair import default_nest_ladder

NEST = '''s32 f(O *p)
{
    s8 v;
    v = 0;
    if ((u8) (p->x + 6) >= 13U) {
        v = 0x3F;
        if (p->x < 0x40) {
            v = -0x3FU;
            if (p->x >= -0x3F) {
                v = p->x;
            }
        }
    }
    return v;
}
'''


def test_a_nest_of_defaults_is_written_as_the_ladder():
    ((family, text),) = default_nest_ladder.variants(NEST, 'f')
    assert family == 'default_nest_ladder'
    assert '''    if ((u8) (p->x + 6) < 13U) {
        v = 0;
    } else if (p->x >= 0x40) {
        v = 0x3F;
    } else if (p->x < -0x3F) {
        v = -0x3FU;
    } else {
        v = p->x;
    }
    return v;''' in text


def test_a_test_that_reads_the_result_is_left_alone():
    assert not default_nest_ladder.variants(NEST.replace('p->x < 0x40', 'v < 0x40'), 'f')


def test_a_default_that_is_not_a_constant_is_left_alone():
    assert not default_nest_ladder.variants(NEST.replace('v = 0x3F;', 'v = g();'), 'f')


def test_one_level_is_left_to_the_default_family():
    source = 'void f(int c)\n{\n    int v;\n    v = 0;\n    if (c) {\n        v = 1;\n    }\n    g(v);\n}\n'
    assert not default_nest_ladder.variants(source, 'f')


def test_a_level_with_an_else_is_left_alone():
    source = NEST.replace('''                v = p->x;
            }''', '''                v = p->x;
            } else {
                v = 1;
            }''')
    assert not default_nest_ladder.variants(source, 'f')
