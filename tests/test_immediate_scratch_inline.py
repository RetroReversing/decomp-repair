"""A scratch local that only carries a value to the next statement, written at that statement."""
from decomprepair import registry
from decomprepair.immediate_scratch_inline import FAMILY, variants

SOURCE = '''void setup(const f32 *p, const f32 *r, f32 h, f32 h2, Segment *out)
{
    f32 y, x, b, c;
    x = p[0];
    y = (x - r[0] * 2.5f) + r[1];
    b = y * h2;
    y = x * -0.5f + r[0] * 0.5f;
    c = y * h;
    y = p[1];
    out->b = b + y;
    out->c = c + y;
}
'''


def test_each_assignment_read_once_by_the_next_statement_is_written_there():
    [(family, text)] = variants(SOURCE, 'setup')
    assert family == FAMILY
    assert '    b = ((x - r[0] * 2.5f) + r[1]) * h2;\n' in text
    assert '    c = (x * -0.5f + r[0] * 0.5f) * h;\n' in text
    assert '    y = p[1];\n' in text  # read by two later statements: stays


def test_a_scratch_read_later_again_is_left_alone():
    assert variants(SOURCE.replace('    c = y * h;\n', '    c = y * h;\n    out->d = y;\n'), 'setup') == [] or \
        '    y = x * -0.5f' in variants(SOURCE.replace('    c = y * h;\n', '    c = y * h;\n    out->d = y;\n'), 'setup')[0][1]


def test_a_function_with_branches_is_left_alone():
    assert variants(SOURCE.replace('    c = y * h;', '    if (h) { c = y * h; }'), 'setup') == []


def test_the_module_declares_itself_to_the_registry():
    assert 'immediate_scratch_inline' in {repair.module for repair in registry.declared()}
    for repair in registry.declared():
        if repair.module == 'immediate_scratch_inline':
            assert registry.problems(repair) == []
