"""float_global_array_read: a float global the target reads through a register, as an unsized array read `G[0]`."""
from decomprepair import float_global_array_read as fgar
from decomprepair import registry

SOURCE = '''s32 func_80043248();
extern f32 D_800099A8;
extern f32 D_801700D0;
s32 func_80083E98(void) {
    s32 temp_v1;
    s32 var_v0;

    temp_v1 = func_80043248();
    do { var_v0 = 2; } while (0);
    if (!(D_801700D0 < D_800099A8)) {
        var_v0 = temp_v1;
    }
    return var_v0;
}
'''
ASM = '''glabel func_80083E98
/* 0 80083EA8 00401821 */  addu       $v1, $v0, $zero
/* 4 80083EAC 3C028017 */  lui        $v0, %hi(D_801700D0)
/* 8 80083EB0 C44200D0 */  lwc1       $fv1, %lo(D_801700D0)($v0)
/* C 80083EB4 3C018001 */  lui        $at, %hi(D_800099A8)
/* 10 80083EB8 C42099A8 */  lwc1       $fv0, %lo(D_800099A8)($at)
'''


def _children():
    return [child for _, child in fgar.variants(SOURCE, 'func_80083E98', asm=ASM)]


def test_the_global_loaded_through_a_register_becomes_an_unsized_array_read():
    children = _children()
    plain = children[0]
    assert 'extern f32 D_801700D0[];' in plain
    assert 'extern f32 D_800099A8;' in plain  # loaded through $at: left alone
    assert 'if (!(D_801700D0[0] < D_800099A8))' in plain


def test_the_read_is_also_held_in_a_local_after_each_statement_down_to_its_use():
    children = _children()
    after_call = [c for c in children if 'held_D_801700D0 = D_801700D0[0];' in c
                  and c.index('held_D_801700D0 = ') > c.index('temp_v1 = func_80043248();')
                  and c.index('held_D_801700D0 = ') < c.index('do {')]
    assert len(after_call) == 1
    child = after_call[0]
    assert 'f32 held_D_801700D0;' in child
    assert 'if (!(held_D_801700D0 < D_800099A8))' in child
    assert any(c.index('held_D_801700D0 = ') < c.index('temp_v1 = func_80043248();') for c in children[1:])


def test_no_proposal_without_the_register_shape_in_the_assembly():
    scalar = ASM.replace('lui        $v0, %hi(D_801700D0)', 'lui        $at, %hi(D_801700D0)').replace(
        '($v0)', '($at)')
    assert fgar.variants(SOURCE, 'func_80083E98', asm=scalar) == []
    assert fgar.variants(SOURCE, 'func_80083E98', asm='') == []


def test_a_written_global_an_integer_and_a_header_declaration_are_left_alone():
    assert fgar.variants(SOURCE.replace('if (!(D_801700D0 <', 'D_801700D0 = 1.0f;\n    if (!(D_801700D0 <'),
                         'func_80083E98', asm=ASM) == []
    assert fgar.variants(SOURCE.replace('extern f32 D_801700D0;', 'extern s32 D_801700D0;'),
                         'func_80083E98', asm=ASM) == []
    assert fgar.variants(SOURCE, 'func_80083E98', header='extern f32 D_801700D0;', asm=ASM) == []


def test_it_declares_itself_to_the_registry():
    assert 'float_global_array_read' in [f for r in registry.declared() for f in r.families]
