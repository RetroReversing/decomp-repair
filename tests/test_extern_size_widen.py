"""extern_size_widen: a small extern scalar the target splits, widened to an array above the -G threshold."""
from decomprepair import extern_size_widen as esw
from decomprepair import registry

SOURCE = '''extern f32 D_8000949C;
extern s32 D_800B9ECC;

f32 func_8007AAE0(f32 arg0) {
    return (f32) D_800B9ECC * arg0 + D_8000949C;
}
'''
ASM = '''glabel func_8007AAE0
/* 0 8007AAE0 3C02800C */  lui        $v0, %hi(D_800B9ECC)
/* 4 8007AAE4 8C439ECC */  lw         $v1, %lo(D_800B9ECC)($v0)
/* 8 8007AAE8 3C01800A */  lui        $at, %hi(D_8000949C)
/* C 8007AAEC C4224000 */  lwc1       $f2, %lo(D_8000949C)($at)
'''
NAME = 'func_8007AAE0'
G4 = ('-G4', '-mips2', '-O2')


def _children(source=SOURCE, asm=ASM, flags=G4, **kw):
    return [child for _, child in esw.variants(source, NAME, asm=asm, flags=flags, **kw)]


def test_the_threshold_is_read_from_the_flags_and_absent_means_none():
    assert esw.threshold(['-G0', '-O2']) == 0 and esw.threshold(['-O2', '-G', '8']) == 8
    assert esw.threshold('-G4 -mips2') == 4 and esw.threshold(['-O2']) is None and esw.threshold(['-G0', '-G8']) == 8


def test_the_global_the_target_splits_becomes_a_two_word_array_read_at_zero():
    children = _children()
    assert len(children) == 1
    assert 'extern s32 D_800B9ECC[2];' in children[0] and '(f32) D_800B9ECC[0] * arg0' in children[0]
    assert 'extern f32 D_8000949C;' in children[0]  # (the float the target reaches through $at stays scalar)


def test_a_wider_threshold_needs_more_elements():
    assert 'extern s32 D_800B9ECC[3];' in _children(flags=('-G8',))[0]
    assert 'extern s16 D_800B9ECC[5];' in _children(SOURCE.replace('extern s32', 'extern s16'), flags=('-G8',))[0]


def test_no_proposal_at_g0_without_a_g_flag_or_for_a_global_not_split_or_too_large():
    assert _children(flags=('-G0', '-O2')) == [] and _children(flags=('-O2',)) == []
    assert _children(asm=ASM.replace('lui        $v0, %hi(D_800B9ECC)', 'lui        $at, %hi(D_800B9ECC)')) == []
    assert _children(asm=ASM + '/* 10 0 */  lw $a0, %gp_rel(D_800B9ECC)($gp)\n') == []
    assert _children(SOURCE.replace('extern s32', 'extern f64')) == []  # (8 bytes: already above -G4 or not a scalar here)
    assert _children(flags=('-G2',)) == []  # (4 bytes is already above -G2)


def test_a_written_global_a_header_declaration_and_another_users_are_left_alone():
    assert _children(SOURCE.replace('* arg0', '* arg0 + (D_800B9ECC = 1)')) == []
    assert _children(header='extern s32 D_800B9ECC;') == []
    assert _children(SOURCE + 'void other(void) { D_800B9ECC = 0; }\n') == []
    assert _children(SOURCE.replace('(f32) D_800B9ECC', '(f32) *&D_800B9ECC')) == []


def test_two_split_globals_get_each_and_the_combined_child():
    source = SOURCE.replace('extern f32 D_8000949C;', 'extern s32 D_8000949C;').replace('+ D_8000949C', '+ (f32) D_8000949C')
    asm = ASM.replace('lui        $at, %hi(D_8000949C)', 'lui        $a0, %hi(D_8000949C)')
    children = _children(source, asm)
    assert len(children) == 3
    assert 'D_8000949C[2]' in children[2] and 'D_800B9ECC[2]' in children[2]


def test_it_declares_itself_to_the_registry():
    assert 'extern_size_widen' in [f for r in registry.declared() for f in r.families]
