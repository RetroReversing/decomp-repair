"""A local that only one arm of a test on a parameter assigns, given the parameter on the other path."""
import re

from decomprepair import registry
from decomprepair.arm_local_parameter_default import FAMILY, variants

# the shape of an m2c draft of a KMC GCC 2.7.2 N64 function (75 -> 0 with the copy before the test)
DRAFT = '''s32 func_80085754(void *arg0, void *arg1, f32 arg2) {
    u8 sp[24];
    s32 var_a2;
    void *var_a1;

    if ((arg1) == NULL) {
        sp0 = 1;
        sp4 = &sp8;
        var_a1 = sp;
        sp14 = (*(f32 *)((s8 *)arg0 + 0x48));
    }
    var_a2 = (*(u16 *)((s8 *)var_a1 + 0));
    return var_a2;
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def children(source, name='func_80085754'):
    return [squash(text) for fam, text in variants(source, name)]


def test_the_copy_before_the_test_comes_first():
    found = children(DRAFT)
    assert len(found) == 3
    assert 'void *var_a1; var_a1 = arg1; if ((arg1) == NULL) {' in found[0]
    assert all(FAMILY == fam for fam, _ in variants(DRAFT, 'func_80085754'))


def test_the_declaration_initialiser_and_the_other_arm_follow():
    found = children(DRAFT)
    assert 'void *var_a1 = arg1; if ((arg1) == NULL) {' in found[1]
    assert '} else { var_a1 = arg1; } var_a2 =' in found[2]


def test_an_existing_else_gets_the_copy_at_its_start():
    text = DRAFT.replace('sp14 = (*(f32 *)((s8 *)arg0 + 0x48));\n    }',
                         'sp14 = (*(f32 *)((s8 *)arg0 + 0x48));\n    } else {\n        sp0 = 2;\n    }')
    assert '} else { var_a1 = arg1; sp0 = 2; }' in children(text)[2]


def test_a_negated_test_is_read_too():
    assert len(children(DRAFT.replace('(arg1) == NULL', '!arg1'))) == 3


def test_a_parameter_that_is_written_is_left_alone():
    assert children(DRAFT.replace('sp0 = 1;', 'sp0 = 1;\n        arg1 = 0;')) == []


def test_a_local_assigned_in_both_arms_or_before_is_left_alone():
    both = DRAFT.replace('sp14 = (*(f32 *)((s8 *)arg0 + 0x48));\n    }',
                         'sp14 = 0;\n    } else {\n        var_a1 = arg0;\n    }')
    assert children(both) == []
    assert children(DRAFT.replace('    if ((arg1)', '    var_a1 = arg0;\n    if ((arg1)')) == []


def test_a_local_never_read_after_the_join_or_of_another_type_is_left_alone():
    assert children(DRAFT.replace('(s8 *)var_a1 + 0', '(s8 *)arg0 + 0')) == []
    assert children(DRAFT.replace('void *var_a1;', 's32 *var_a1;')) == []


def test_a_test_on_the_local_itself_is_left_alone():
    assert children(DRAFT.replace('(arg1) == NULL', 'var_a1 == NULL')) == []


def test_it_is_registered():
    assert registry.get("arm_local_parameter_default") is not None
