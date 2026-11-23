"""arm_operand_pre_stage: a scaled operand of one arm's call computed above the branch."""
from decomprepair import arm_operand_pre_stage as a
from decomprepair import registry

DRAFT = '''extern s32 gHiRes;
void rect(s32 *g, s32 x, s32 y, s32 z);
void f(s32 *g, s32 arg0, s32 arg1)
{
    s32 var_t7;
    s32 temp_a1;

    var_t7 = arg0;
    temp_a1 = arg1 * 4;
    if (gHiRes != 0) {
        rect(g, temp_a1, var_t7 * 8, 0x400);
    } else {
        rect(g, temp_a1, var_t7 * 4, 0x400);
    }
}
'''


def test_an_operand_one_arm_scales_is_staged_above_the_branch():
    out = a.variants(DRAFT, 'f')
    assert {family for family, _ in out} == {'arm_operand_pre_stage'}
    child = next(c for _, c in out if 'staged_var_t7 = var_t7 * 4; if' in c and c.count(' = var_t7 * ') == 1)
    assert 'staged_var_t7 = var_t7 * 4; if (gHiRes != 0)' in child
    assert 'rect(g, temp_a1, var_t7 * 8, 0x400);' in child and 'rect(g, temp_a1, staged_var_t7, 0x400);' in child
    assert 's32 staged_var_t7;' in child


def test_an_operand_the_other_arm_does_not_name_is_not_staged():
    source = DRAFT.replace('rect(g, temp_a1, var_t7 * 8, 0x400);', 'rect(g, temp_a1, arg0 * 8, 0x400);')
    assert all('staged_var_t7 = ' not in child for _, child in a.variants(source, 'f'))


def test_a_condition_that_assigns_or_an_else_if_is_left_alone():
    assert a.variants(DRAFT.replace('gHiRes != 0', 'var_t7 = gHiRes'), 'f') == []
    chained = DRAFT.replace('    } else {\n        rect(g, temp_a1, var_t7 * 4, 0x400);\n    }',
                            '    } else if (arg1) {\n        rect(g, temp_a1, var_t7 * 4, 0x400);\n    } else {\n        rect(g, 0, 0, 0);\n    }')
    assert all('staged_var_t7 = var_t7 * 4; if (arg1)' not in child for _, child in a.variants(chained, 'f'))


def test_the_module_declares_itself_to_the_registry():
    assert any(r.module == 'arm_operand_pre_stage' for r in registry.declared())
