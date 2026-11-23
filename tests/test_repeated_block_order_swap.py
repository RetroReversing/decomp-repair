"""The same two neighbouring assignments swapped in every block that repeats them."""
from decomprepair import registry
from decomprepair.repeated_block_order_swap import FAMILY, ONE_FAMILY, variants

SOURCE = '''void setup(const f32 *p, const f32 *q, f32 h2, f32 h3, Segment *out)
{
    f32 a, b, c;
    b = (p[0] - q[0] * 2.5f) * h2;
    a = (p[0] * -0.5f + q[0] * 1.5f) * h3;
    c = p[0] * 0.5f;
    out->x = a + b + c;
    b = (p[1] - q[1] * 2.5f) * h2;
    a = (p[1] * -0.5f + q[1] * 1.5f) * h3;
    c = p[1] * 0.5f;
    out->y = a + b + c;
    b = (p[2] - q[2] * 2.5f) * h2;
    a = (p[2] * -0.5f + q[2] * 1.5f) * h3;
    c = p[2] * 0.5f;
    out->z = a + b + c;
}
'''


def test_the_pair_is_swapped_in_every_block_at_once():
    found = [text for family, text in variants(SOURCE, 'setup') if family == FAMILY]
    assert len(found) == 2  # the (b, a) pair and the (a, c) pair each repeat three times
    text = next(text for text in found if text.index('    a = (p[0]') < text.index('    b = (p[0]'))
    assert text.count('    a = (p[') == 3
    for axis in '012':
        assert text.index(f'    a = (p[{axis}]') < text.index(f'    b = (p[{axis}]') < text.index(f'    c = p[{axis}]')
    assert text.count('\n') == SOURCE.count('\n')


def test_each_single_occurrence_is_offered_apart():
    one = [text for family, text in variants(SOURCE, 'setup') if family == ONE_FAMILY]
    assert len(one) >= 3
    assert any(text.index('    a = (p[0]') < text.index('    b = (p[0]') and text.index('    b = (p[1]') < text.index('    a = (p[1]')
               for text in one)


def test_dependent_or_calling_neighbours_are_left_alone():
    dependent = SOURCE.replace('b = (p[0] - q[0] * 2.5f) * h2;', 'b = (a - q[0] * 2.5f) * h2;')
    assert all('a = (p[0]' not in text.split('b = (a')[0] for _, text in variants(dependent, 'setup'))
    calling = SOURCE.replace('* h3;', '* get(h3);')
    assert variants(calling, 'setup') == []


def test_the_module_declares_itself_to_the_registry():
    assert 'repeated_block_order_swap' in {repair.module for repair in registry.declared()}
    for repair in registry.declared():
        if repair.module == 'repeated_block_order_swap':
            assert registry.problems(repair) == []
