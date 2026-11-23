"""A `volatile` output record that the function only writes, written as a plain pointer."""
from decomprepair import registry
from decomprepair.volatile_output_parameter_plain import FAMILY, variants

SOURCE = '''void fill(const f32 *p, s32 n, volatile Segment *out)
{
    out->n = n;
    out->x.f = p[0];
    out->v[1] = p[1];
}
'''


def test_a_stored_only_volatile_pointer_parameter_loses_its_qualifier():
    assert variants(SOURCE, 'fill') == [(FAMILY, SOURCE.replace('volatile ', ''))]


def test_a_parameter_that_is_read_passed_on_or_compared_keeps_it():
    for read in ('out->x.f = out->n;', 'use(out);', 'if (out == 0) { return; }'):
        assert variants(SOURCE.replace('out->x.f = p[0];', read), 'fill') == []


def test_a_parameter_that_is_not_volatile_has_no_child():
    assert variants(SOURCE.replace('volatile ', ''), 'fill') == []


def test_the_module_declares_itself_to_the_registry():
    assert 'volatile_output_parameter_plain' in {repair.module for repair in registry.declared()}
    for repair in registry.declared():
        if repair.module == 'volatile_output_parameter_plain':
            assert registry.problems(repair) == []
