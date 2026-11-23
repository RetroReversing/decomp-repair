from decomprepair import nested_assign_call_arms as repair
from decomprepair import registry

SOURCE = '''void f(void *p, f32 a, f32 b, f32 c)
{
    s32 v;
    if (a < b - 1.0f)
    {
        v = 0x17;
    }
    else
    {
        v = 0x1A;
        if (!((b + 1.0f) < a))
        {
            v = 0x1B;
        }
    }
    g(p, v, 0x1B);
}
'''


def texts(source=SOURCE):
    return [t for _, t in repair.variants(source, 'f')]


def test_the_call_is_made_in_each_leaf_with_the_literal_in_place():
    found = texts()
    as_written = next(t for t in found if 'if (!((b + 1.0f) < a))' in t)
    assert 'g(p, 0x17, 0x1B);' in as_written and 'g(p, 0x1B, 0x1B);' in as_written and 'g(p, 0x1A, 0x1B);' in as_written
    assert 'g(p, v, 0x1B);' not in as_written


def test_the_negated_condition_is_offered_with_its_arms_swapped_as_an_else_if():
    found = texts()
    flipped = next(t for t in found if '(b + 1.0f) < a' in t and 'if (!((b + 1.0f) < a))' not in t)
    assert 'else\n    if ((b + 1.0f) < a)' in flipped
    assert flipped.index('g(p, 0x1A, 0x1B);') < flipped.index('g(p, 0x1B, 0x1B);')


def test_a_variable_read_after_the_call_or_set_before_the_tree_is_left_alone():
    after = SOURCE.replace('    g(p, v, 0x1B);\n', '    g(p, v, 0x1B);\n    h(v);\n')
    assert not texts(after)
    before = SOURCE.replace('    if (a < b - 1.0f)\n', '    v = 5;\n    if (a < b - 1.0f)\n', 1)
    assert not texts(before)


def test_a_path_that_never_sets_the_variable_is_left_alone():
    unset = SOURCE.replace('        v = 0x17;\n', '        h();\n')
    assert not texts(unset)


def test_it_is_declared_for_every_lane():
    declared = registry.get('nested_assign_call_arms')
    assert declared is not None and registry.problems(declared) == []
    assert registry.run('nested_assign_call_arms', source=SOURCE, name='f')
