"""int_global_array_read: an integer global whose address the target builds early, as a byte array read through a cast."""
from decomprepair import int_global_array_read as igar
from decomprepair import registry

SOURCE = '''s16 coss(s32);
extern f32 D_8000086C;
extern s32 D_800B9EA4;

void func_80015F80(void *arg0) {
    M2C_FIELD(arg0, f32 *, 4) = (f32) coss(((M2C_FIELD(arg0, s32 *, 0x8C) + D_800B9EA4) * 0x320) & 0xFFE0);
}
'''
ASM = '''glabel func_80015F80
/* 0 80015F80 27BDFFE8 */  addiu      $sp, $sp, -0x18
/* 4 80015F84 AFB00010 */  sw         $s0, 0x10($sp)
/* 8 80015F88 00808021 */  addu       $s0, $a0, $zero
/* C 80015F8C 3C02800C */  lui        $v0, %hi(D_800B9EA4)
/* 10 80015F90 AFBF0014 */  sw         $ra, 0x14($sp)
/* 14 80015F94 8E03008C */  lw         $v1, 0x8C($s0)
/* 18 80015F98 8C429EA4 */  lw         $v0, %lo(D_800B9EA4)($v0)
'''
NAME = 'func_80015F80'


def _children(source=SOURCE, asm=ASM, **kw):
    return [child for _, child in igar.variants(source, NAME, asm=asm, **kw)]


def test_the_hoisted_integer_global_becomes_a_byte_array_read_through_a_cast():
    first = _children()[0]
    assert 'extern u8 D_800B9EA4[];' in first
    assert '(M2C_FIELD(arg0, s32 *, 0x8C) + *(s32 *) D_800B9EA4)' in first
    assert 'extern f32 D_8000086C;' in first


def test_the_array_of_its_own_type_read_at_zero_is_the_second_child():
    second = _children()[1]
    assert 'extern s32 D_800B9EA4[];' in second
    assert '+ D_800B9EA4[0])' in second


def test_a_byte_global_gets_one_child_and_a_pointer_global_is_read_through_a_pointer_cast():
    byte = _children(SOURCE.replace('extern s32 D_800B9EA4;', 'extern u8 D_800B9EA4;'))
    assert len(byte) == 1 and 'extern u8 D_800B9EA4[];' in byte[0] and '*(u8 *) D_800B9EA4' in byte[0]
    pointer = _children(SOURCE.replace('extern s32 D_800B9EA4;', 'extern void *D_800B9EA4;'))
    assert 'extern u8 D_800B9EA4[];' in pointer[0] and '*(void **) D_800B9EA4' in pointer[0]


def test_two_globals_also_get_the_combined_children():
    source = SOURCE.replace('extern s32 D_800B9EA4;', 'extern s32 D_800B9EA4;\nextern u16 D_800B9EB0;').replace(
        '& 0xFFE0)', '& 0xFFE0) + D_800B9EB0')
    asm = ASM + '/* 1C 80015F9C 3C03800C */  lui        $v1, %hi(D_800B9EB0)\n' \
        '/* 20 80015FA0 AFA40018 */  sw         $a0, 0x18($sp)\n' \
        '/* 24 80015FA4 94639EB0 */  lhu        $v1, %lo(D_800B9EB0)($v1)\n'
    children = _children(source, asm)
    assert len(children) == 6
    both = children[4]
    assert 'extern u8 D_800B9EA4[];' in both and 'extern u8 D_800B9EB0[];' in both
    assert '*(s32 *) D_800B9EA4' in both and '*(u16 *) D_800B9EB0' in both
    assert 'extern s32 D_800B9EA4[];' in children[5] and 'extern u16 D_800B9EB0[];' in children[5] and 'D_800B9EB0[0]' in children[5]


def test_no_proposal_for_a_scalar_load_the_target_keeps_beside_its_lui():
    adjacent = ASM.replace('/* 10 80015F90 AFBF0014 */  sw         $ra, 0x14($sp)\n', '').replace(
        '/* 14 80015F94 8E03008C */  lw         $v1, 0x8C($s0)\n', '')
    assert igar.variants(SOURCE, NAME, asm=adjacent) == []
    assert igar.variants(SOURCE, NAME, asm='') == []


def test_no_proposal_for_an_address_built_in_at_or_read_through_gp():
    at = ASM.replace('lui        $v0, %hi(D_800B9EA4)', 'lui        $at, %hi(D_800B9EA4)')
    assert igar.variants(SOURCE, NAME, asm=at) == []
    gp = ASM + '/* 1C 0 */  lw         $a1, %gp_rel(D_800B9EA4)($gp)\n'
    assert igar.variants(SOURCE, NAME, asm=gp) == []


def test_a_written_global_a_float_a_header_declaration_and_another_users_are_left_alone():
    assert igar.variants(SOURCE.replace('+ D_800B9EA4)', '+ D_800B9EA4) + (D_800B9EA4 = 1)'), NAME, asm=ASM) == []
    assert igar.variants(SOURCE.replace('extern s32 D_800B9EA4;', 'extern f32 D_800B9EA4;'), NAME, asm=ASM) == []
    assert igar.variants(SOURCE, NAME, header='extern s32 D_800B9EA4;', asm=ASM) == []
    other = SOURCE + 'void other(void) { D_800B9EA4 = 0; }\n'
    assert igar.variants(other, NAME, asm=ASM) == []
    assert igar.variants(SOURCE.replace('D_800B9EA4)', '&D_800B9EA4)'), NAME, asm=ASM) == []


def test_it_declares_itself_to_the_registry():
    assert 'int_global_array_read' in [f for r in registry.declared() for f in r.families]
