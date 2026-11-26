from decomprepair import constant_index_opaque as family

LITERAL = '''void f(u32 arg0)
{
    if (G[arg0].flag == 0) {
        D[2].a = 0;
        D[2].b = 0;
        D[2].c = 0;
        G[arg0].flag = 1;
    }
}
'''


def test_a_repeated_literal_index_is_named_and_kept_from_folding():
    ((name, text),) = family.variants(LITERAL, 'f')
    assert name == 'constant_index_opaque'
    assert '''        record_index = 2;
        unused_choice = arg0 ? 1 : 2;
        D[record_index].a = 0;
        D[record_index].b = 0;''' in text
    assert 'int record_index;' in text and 'int unused_choice;' in text


def test_a_constant_index_local_gets_the_dead_choice_after_its_set():
    source = 'void f(int a)\n{\n    int i;\n    i = 2;\n    D[i].a = 0;\n}\n'
    ((_, text),) = family.variants(source, 'f')
    assert '    i = 2;\n    unused_choice = a ? 1 : 2;\n    D[i].a = 0;' in text


def test_a_function_without_a_parameter_is_left_alone():
    assert not family.variants(LITERAL.replace('u32 arg0', 'void'), 'f')


def test_array_declarations_and_rare_literals_are_left_alone():
    source = 'void f(int a)\n{\n    int x[3];\n    int y[3];\n    int z[3];\n    D[3].a = a;\n}\n'
    assert not family.variants(source, 'f')


def test_a_local_that_is_no_index_is_left_alone():
    assert not family.variants('int f(int a)\n{\n    int i;\n    i = 2;\n    return i + a;\n}\n', 'f')
