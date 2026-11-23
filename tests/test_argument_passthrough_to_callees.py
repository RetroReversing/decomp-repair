"""The caller's own arguments passed on to every callee that receives them untouched."""
import re

from decomprepair import registry
from decomprepair.argument_passthrough_to_callees import FAMILY, incoming_calls, variants

# the m2c draft of a KMC GCC 2.7.2 N64 dispatcher (10 -> 0 with the first child) and its target
DRAFT = '''typedef int s32;
typedef s32 M2C_UNK;

M2C_UNK func_80023E58();                            /* extern */
M2C_UNK func_80024130();                            /* extern */

void func_800242A8(s32 arg2) {
    if (!(arg2 & 0x10)) {
        func_80024130();
        return;
    }
    func_80023E58();
}
'''

ASM = '''glabel func_800242A8
/* 24EA8 800242A8 27BDFFE8 */  addiu      $sp, $sp, -0x18
/* 24EAC 800242AC 30C20010 */  andi       $v0, $a2, 0x10
/* 24EB0 800242B0 14400005 */  bnez       $v0, .L800242C8
/* 24EB4 800242B4 AFBF0010 */  sw         $ra, 0x10($sp)
/* 24EB8 800242B8 0C00904C */  jal        func_80024130
/* 24EBC 800242BC 00000000 */  nop
/* 24EC0 800242C0 080090B4 */  j          .L800242D0
/* 24EC4 800242C4 00000000 */  nop
.L800242C8:
/* 24EC8 800242C8 0C008F96 */  jal        func_80023E58
/* 24ECC 800242CC 00000000 */  nop
.L800242D0:
/* 24ED0 800242D0 8FBF0010 */  lw         $ra, 0x10($sp)
/* 24ED4 800242D4 03E00008 */  jr         $ra
/* 24ED8 800242D8 27BD0018 */  addiu      $sp, $sp, 0x18
endlabel func_800242A8
'''

MATCHED = ('void func_800242A8(s32 arg0, s32 arg1, s32 arg2) { if (!(arg2 & 0x10)) { func_80024130(arg0, arg1, arg2); '
           'return; } func_80023E58(arg0, arg1, arg2); }')


def squash(text):
    return re.sub(r'\s+', ' ', text)


def children(source=DRAFT, asm=ASM, name='func_800242A8', **context):
    return [squash(text) for _, text in variants(source, name, asm=asm, arch='mips', **context)]


def test_the_draft_gets_the_matching_source_first():
    found = children()
    assert MATCHED in found[0]
    assert 'func_800242A8(s32 arg0, s32 arg1, s32 arg2, s32 arg3)' in found[1]
    assert len(found) == 2


def test_registers_are_followed_across_the_branch():
    assert incoming_calls(ASM) == {'func_80024130': {0, 1, 2, 3}, 'func_80023E58': {0, 1, 2, 3}}


def test_a_register_written_on_one_path_stops_the_count_there():
    # $a1 rewritten on the path to the second call: only $a0 reaches both calls, fewer than the parameter needs
    asm = ASM.replace('.L800242C8:\n', '.L800242C8:\n/* 0 */  addiu $a1, $zero, 0x5\n')
    assert incoming_calls(asm)['func_80023E58'] == {0, 2, 3}
    assert children(asm=asm) == []
    # a register written in the branch's delay slot is written on both paths
    asm = ASM.replace('sw         $ra, 0x10($sp)', 'move $a2, $zero')
    assert children(asm=asm) == []


def test_an_earlier_call_clobbers_the_arguments():
    asm = ASM.replace('/* 24EAC 800242AC', '/* 0 */  jal func_80001000\n/* 0 */  nop\n/* 24EAC 800242AC')
    assert incoming_calls(asm)['func_80024130'] == set()
    assert children(asm=asm) == []


def test_a_parameter_written_in_the_body_is_left_alone():
    assert children(DRAFT.replace('return;', 'arg2 = 0;\n        return;')) == []
    assert children(DRAFT.replace('func_80023E58();', 'arg2++;\n    func_80023E58();')) == []


def test_a_callee_with_a_prototype_or_a_call_with_arguments_is_left_alone():
    prototyped = DRAFT.replace('M2C_UNK func_80024130();', 'M2C_UNK func_80024130(void);').replace(
        'M2C_UNK func_80023E58();', 'M2C_UNK func_80023E58(s32);')
    assert children(prototyped) == []
    assert children(DRAFT, header='M2C_UNK func_80024130(s32 a);\nM2C_UNK func_80023E58(s32 a);') == []
    # one callee declared with parameters: the other still gets them
    one = children(DRAFT.replace('M2C_UNK func_80023E58();', 'M2C_UNK func_80023E58(s32);'))
    assert 'func_80024130(arg0, arg1, arg2);' in one[0] and 'func_80023E58();' in one[0]


def test_named_or_float_parameters_are_left_alone():
    assert children(DRAFT.replace('(s32 arg2)', '(s32 mode)').replace('arg2 &', 'mode &')) == []
    assert children(DRAFT.replace('(s32 arg2)', '(f32 arg2)')) == []


def test_without_the_target_or_on_another_processor_nothing_is_offered():
    assert variants(DRAFT, 'func_800242A8', asm='', arch='mips') == []
    assert variants(DRAFT, 'func_800242A8', asm=ASM, arch='x86') == []


def test_an_indirect_jump_ends_the_proof():
    asm = ASM.replace('jr         $ra', 'jr         $t9')
    assert incoming_calls(asm) == {}


def test_the_family_declares_itself_to_the_registry():
    [repair] = [item for item in registry.declared() if FAMILY in item.families]
    assert registry.problems(repair) == []
