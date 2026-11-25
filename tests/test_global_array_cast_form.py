"""global_array_cast_form: a small-data global the target splits, as a byte array read through a cast (members too)."""
from decomprepair import global_array_cast_form as gacf
from decomprepair import registry

SOURCE = '''typedef struct Obj { s32 x0; s32 x4; s32 x8; } Obj;
extern Obj *D_800B3960;
extern s32 D_800B9ECC;
void func_80011D30(Obj *arg0) {
    arg0->x4 = 1;
    arg0->x0 = D_800B3960->x8 + D_800B9ECC;
}
'''
ASM = '''glabel func_80011D30
/* 0 80011D30 27BDFFE8 */  addiu      $sp, $sp, -0x18
/* 4 80011D34 3C0E800B */  lui        $t6, %hi(D_800B3960)
/* 8 80011D38 24080001 */  addiu      $t0, $zero, 1
/* C 80011D3C AC880004 */  sw         $t0, 4($a0)
/* 10 80011D40 8DCF3960 */  lw         $t7, %lo(D_800B3960)($t6)
/* 14 80011D44 3C09800B */  lui        $t1, %hi(D_800B9ECC)
/* 18 80011D48 8D2A9ECC */  lw         $t1, %lo(D_800B9ECC)($t1)
'''
NAME = 'func_80011D30'
FLAGS = ('-G8', '-mips3', '-O2')


def children(source=SOURCE, asm=ASM, flags=FLAGS, header=''):
    return [child for _, child in gacf.variants(source, NAME, header, asm, flags)]


def test_a_pointer_global_read_through_a_member_is_a_byte_array_read_through_a_cast_first():
    out = children()
    assert 'extern u8 D_800B3960[];' in out[0] and '(*(Obj **) D_800B3960)->x8' in out[0]
    assert 'extern s32 D_800B9ECC;' in out[0]  # the integer global the target did not split stays
    assert 'extern Obj *D_800B3960[];' in out[1] and 'D_800B3960[0]->x8' in out[1]


def test_every_global_the_target_splits_has_a_child_alone_and_together():
    asm = ASM.replace('lw         $t1, %lo(D_800B9ECC)($t1)', 'sw         $t2, 8($a0)\n/* 1C 80011D4C 8D2A9ECC */  lw         $t3, %lo(D_800B9ECC)($t1)')
    out = children(asm=asm)
    both = [c for c in out if 'extern u8 D_800B3960[];' in c and 'extern u8 D_800B9ECC[];' in c]
    assert len(both) == 1 and '(*(s32 *) D_800B9ECC)' in both[0] and '(*(Obj **) D_800B3960)->x8' in both[0]
    assert any('extern u8 D_800B9ECC[];' in c and 'extern u8 D_800B3960[];' not in c for c in out)
    assert len(out) <= gacf.MAX_CHILDREN


def test_the_profile_must_name_a_g_size_that_holds_the_global():
    assert children(flags=('-G0', '-O2')) == [] and children(flags=('-O2',)) == []
    assert children(SOURCE.replace('extern Obj *D_800B3960;', 'extern Obj *D_800B3960;\nextern f64 D_800B9ED0;'),
                    flags=('-G4',))  # the pointer fits 4 bytes


def test_a_global_read_in_one_macro_is_not_split_and_gets_nothing():
    adjacent = ASM.replace('/* 8 80011D38 24080001 */  addiu      $t0, $zero, 1\n/* C 80011D3C AC880004 */  sw         $t0, 4($a0)\n', '') \
        .replace('lw         $t7, %lo(D_800B3960)($t6)', 'lw         $t6, %lo(D_800B3960)($t6)')
    assert children(asm=adjacent) == []
    via_at = ASM.replace('$t6', '$at')
    assert children(asm=via_at) == []


def test_a_written_global_or_one_with_its_address_taken_is_left_alone():
    assert children(SOURCE.replace('arg0->x4 = 1;', 'D_800B3960 = arg0;')) == []
    assert children(SOURCE.replace('arg0->x4 = 1;', 'func(&D_800B3960);')) == []
    assert children(SOURCE + 'void other(void) { D_800B3960 = 0; }\n') == []
    assert children(header='extern Obj *D_800B3960;') == []


def test_a_plain_read_the_sibling_already_takes_is_not_offered_again():
    plain = SOURCE.replace('D_800B3960->x8', 'D_800B3960').replace('Obj *D_800B3960', 'void *D_800B3960')
    assert children(plain) == []  # int_global_array_read.early_address already fires on it
    shared = ASM.replace('lw         $t7, %lo(D_800B3960)($t6)', 'lw         $t7, %lo(D_800B3960)($t6)')
    assert children(plain, shared.replace('/* 8 80011D38 24080001 */  addiu      $t0, $zero, 1\n/* C 80011D3C AC880004 */  sw         $t0, 4($a0)\n', '')
                    .replace('lw         $t7, %lo(D_800B3960)($t6)', 'lw         $t7, %lo(D_800B3960)($t6)\n/* 12 80011D42 8DD83960 */  lw         $t8, %lo(D_800B3960)($t6)'))


def test_it_is_registered_and_declares_what_it_needs():
    repair = {r.module: r for r in registry.declared()}['global_array_cast_form']
    assert not registry.problems(repair)
    assert repair.families == ('global_array_cast_form',) and set(repair.needs) >= {'asm', 'flags'}


def test_the_address_of_a_member_through_the_pointer_is_still_a_read_of_the_pointer():
    out = children(SOURCE.replace('arg0->x4 = 1;', 'func(&D_800B3960->x4);'))
    assert out and '&(*(Obj **) D_800B3960)->x4' in out[0]
