"""A constant result set in a branch with its default in a second, never-read local: explicit returns."""
import pytest

from decomprepair import registry
from decomprepair.entry_default_constant_returns import FAMILY, variants

DRAFT = '''s32 g(s32);
s32 f(s32 a) {
    s32 var_v0;
    s32 var_v0_entry;
    s32 temp_s0;

    temp_s0 = g(a);
    var_v0_entry = 0;
    if (temp_s0 == 3) {
        g(temp_s0);
        var_v0 = 1;
    }
    return var_v0;
}
'''
WANT = '''s32 g(s32);
s32 f(s32 a) {
    s32 temp_s0;

    temp_s0 = g(a);
    if (temp_s0 == 3) {
        g(temp_s0);
        return 1;
    }
    return 0;
}
'''


def _kids(text):
    return [s for fam, s in variants(text, 'f') if fam == FAMILY]


def test_each_assignment_returns_and_the_end_returns_the_entry_constant():
    assert _kids(DRAFT) == [WANT]


def test_two_branches_and_a_hex_default():
    text = DRAFT.replace('var_v0_entry = 0;', 'var_v0_entry = 0x10;').replace(
        '        var_v0 = 1;\n    }\n', '        if (a) {\n            var_v0 = 2;\n        }\n    }\n')
    kids = _kids(text)
    assert len(kids) == 1
    assert 'return 2;' in kids[0] and kids[0].rstrip().endswith('return 0x10;\n}')
    assert 'var_v0' not in kids[0]


@pytest.mark.parametrize('swap', [
    ('    var_v0_entry = 0;\n', '    var_v0_entry = 0;\n    g(var_v0_entry);\n'),        # the entry local is read
    ('        var_v0 = 1;\n', '        var_v0 = g(1);\n'),                              # not a constant
    ('        var_v0 = 1;\n', '        var_v0 = 1;\n        g(0);\n'),                    # code after the assignment
    ('    return var_v0;', '    return var_v0 + 1;'),                                    # not a plain return
])
def test_shapes_it_must_leave_alone(swap):
    assert _kids(DRAFT.replace(*swap)) == []


def test_a_result_that_is_its_own_default_is_the_older_familys():
    text = DRAFT.replace('    s32 var_v0_entry;\n', '').replace('    var_v0_entry = 0;\n', '    var_v0 = 0;\n')
    assert _kids(text) == []


def test_it_is_declared_for_the_registry():
    ours = [r for r in registry.declared() if FAMILY in r.families]
    assert len(ours) == 1 and registry.problems(ours[0]) == []
