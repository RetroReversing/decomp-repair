"""A pointer parameter copied into a local inside each arm of the `if` that tests it."""
import re

from decomprepair import registry
from decomprepair.arm_pointer_parameter_copy import FAMILY, variants

# the m2c draft of a KMC GCC 2.7.2 N64 function (10 -> 0 with the first child)
DRAFT = '''typedef int s32;
typedef s32 M2C_UNK;
#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))

M2C_UNK func_8004303C();                            /* extern */
M2C_UNK func_80043328(void *, s32, M2C_UNK);        /* extern */

void func_800880B4(void *arg0) {
    s32 var_a1;

    func_8004303C();
    if (M2C_FIELD(arg0, s32 *, 0xC0) != 0) {
        var_a1 = M2C_FIELD(arg0, s32 *, 0x84);
    } else {
        var_a1 = M2C_FIELD(arg0, s32 *, 0x88);
    }
    func_80043328(arg0, var_a1, 0x100);
}
'''

MATCHED = ('void *p; s32 var_a1; func_8004303C(); if (M2C_FIELD(arg0, s32 *, 0xC0) != 0) { p = arg0; '
           'var_a1 = M2C_FIELD(p, s32 *, 0x84); } else { p = arg0; var_a1 = M2C_FIELD(p, s32 *, 0x88); } '
           'func_80043328(p, var_a1, 0x100);')


def squash(text):
    return re.sub(r'\s+', ' ', text)


def children(source, name='func_800880B4'):
    return [squash(text) for _, text in variants(source, name)]


def test_the_draft_gets_the_matching_source_first():
    found = children(DRAFT)
    assert MATCHED in found[0]
    # the second child keeps the call on the parameter
    assert 'func_80043328(arg0, var_a1, 0x100);' in found[1] and 'p = arg0; var_a1 = M2C_FIELD(p' in found[1]
    assert len(found) == 2


def test_the_condition_still_reads_the_parameter():
    assert all('if (M2C_FIELD(arg0, s32 *, 0xC0) != 0)' in text for text in children(DRAFT))


def test_a_parameter_written_in_an_arm_is_left_alone():
    written = DRAFT.replace('var_a1 = M2C_FIELD(arg0, s32 *, 0x84);',
                            'arg0 = M2C_FIELD(arg0, void **, 0x10);\n        var_a1 = M2C_FIELD(arg0, s32 *, 0x84);')
    assert children(written) == []


def test_a_parameter_written_before_the_test_or_after_the_join_is_left_alone():
    assert children(DRAFT.replace('func_8004303C();', 'func_8004303C();\n    arg0 += 4;')) == []
    assert children(DRAFT.replace('func_80043328(arg0,', 'arg0++;\n    func_80043328(arg0,')) == []


def test_a_parameter_whose_address_is_taken_is_left_alone():
    assert children(DRAFT.replace('func_8004303C();', 'func_8004303C(&arg0);')) == []


def test_an_if_without_an_else_or_an_else_if_is_left_alone():
    one_arm = DRAFT.replace(''' else {
        var_a1 = M2C_FIELD(arg0, s32 *, 0x88);
    }''', '')
    assert children(one_arm) == []
    chained = DRAFT.replace('func_8004303C();\n    if', 'func_8004303C();\n    if (var_a1) {\n        var_a1 = 1;\n    } else if')
    assert children(chained) == []


def test_an_arm_that_starts_with_a_declaration_or_misses_the_parameter_is_left_alone():
    declared = DRAFT.replace('{\n        var_a1 = M2C_FIELD(arg0, s32 *, 0x84);', '{\n        s32 t = 1;\n        var_a1 = M2C_FIELD(arg0, s32 *, 0x84) + t;')
    assert children(declared) == []
    assert children(DRAFT.replace('M2C_FIELD(arg0, s32 *, 0x88)', '0x88')) == []


def test_a_condition_that_does_not_read_the_parameter_is_left_alone():
    assert children(DRAFT.replace('M2C_FIELD(arg0, s32 *, 0xC0) != 0', 'var_a1 != 0')) == []


def test_an_integer_parameter_is_left_alone():
    assert children(DRAFT.replace('void func_800880B4(void *arg0)', 'void func_800880B4(s32 arg0)')) == []


def test_uses_after_a_nested_if_are_only_rewritten_inside_its_block():
    nested = DRAFT.replace('    func_8004303C();\n', '    func_8004303C();\n    if (var_a1) {\n').replace(
        '    func_80043328(arg0, var_a1, 0x100);\n}', '    func_80043328(arg0, var_a1, 0x100);\n    }\n    func_8004303C(arg0);\n}')
    first = children(nested)[0]
    assert 'func_80043328(p, var_a1, 0x100); } func_8004303C(arg0);' in first


def test_the_family_declares_itself_to_the_registry():
    [repair] = [item for item in registry.declared() if FAMILY in item.families]
    assert registry.problems(repair) == []
