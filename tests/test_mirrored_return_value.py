"""m2c's second return variable, which always equals the first at every return."""
from decomprepair import mirrored_return_value as mirrored
from decomprepair import registry

SOURCE = '''s32 check(s32 which)
{
    s32 ok;
    s32 result;

    ok = 1;
    if (which != 0) {
        result = 1;
        if (find() == 5) {
            ok = 0;
            goto block_11;
        }
    } else {
block_11:
        result = ok;
    }
    return result;
}
'''


def children(source=SOURCE):
    found = mirrored.variants(source, 'check')
    assert all(family == mirrored.FAMILY for family, _ in found)
    return [text for _, text in found]


def test_the_second_variable_goes_and_the_first_is_returned():
    child, = children()
    assert 'result' not in child
    assert 'return ok;' in child
    assert 'block_11:\n' in child


def test_a_value_that_can_differ_at_the_return_declines():
    assert children(SOURCE.replace('result = 1;', 'result = 2;')) == []
    assert children(SOURCE.replace('            goto block_11;\n', '')) == []


def test_a_variable_read_for_anything_else_declines():
    assert children(SOURCE.replace('if (find() == 5) {', 'if (find(result) == 5) {')) == []


def test_the_family_is_registered():
    assert any(mirrored.FAMILY in repair.families for repair in registry.declared())
