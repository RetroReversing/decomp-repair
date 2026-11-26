"""A prototyped callee called in several arms that the target hands the caller's own leading argument."""
from decomprepair import registry
from decomprepair.leading_argument_widen import FAMILY, variants

DRAFT = '''typedef int s32;

s32 g1();                            /* extern */
s32 g2(s32);                         /* extern */

void f(void *arg0) {
    s32 v;

    switch (*(u16 *)((s8 *)arg0 + 0x24A)) {
    case 1:
        g1();
        return;
    case 8:
        v = 0x12C;
        g2(v);
        break;
    default:
        v = 0x1B8;
        if (*(s16 *)((s8 *)arg0 + 0x11C) == 0xE) {
            g2(v);
        }
        break;
    }
}
'''

# a jump table (`jr $v0`): the walk cannot follow it, and one `jal g2` stands for both calls (cross-jumping)
ASM = '''glabel f
/* 0 80000000 27BDFFE8 */  addiu      $sp, $sp, -0x18
/* 4 80000004 AFBF0010 */  sw         $ra, 0x10($sp)
/* 8 80000008 9482024A */  lhu        $v0, 0x24A($a0)
/* C 8000000C 2443FFFF */  addiu      $v1, $v0, -0x1
/* 10 80000010 2C62000C */  sltiu      $v0, $v1, 0xC
/* 14 80000014 1040001C */  beqz       $v0, .L80000040
/* 18 80000018 00031080 */  sll        $v0, $v1, 2
/* 1C 8000001C 8C227440 */  lw         $v0, %lo(jtbl_80027440)($at)
/* 20 80000020 00400008 */  jr         $v0
/* 24 80000024 00000000 */  nop
/* 28 80000028 0C01BE90 */  jal        g1
/* 2C 8000002C 00000000 */  nop
/* 30 80000030 0801BB88 */  j          .L80000060
/* 34 80000034 00000000 */  nop
.L80000040:
/* 38 80000040 2405012C */  addiu      $a1, $zero, 0x12C
/* 3C 80000044 0C01C547 */  jal        g2
/* 40 80000048 00000000 */  nop
.L80000060:
/* 44 80000060 8FBF0010 */  lw         $ra, 0x10($sp)
/* 48 80000064 03E00008 */  jr         $ra
/* 4C 80000068 27BD0018 */  addiu      $sp, $sp, 0x18
endlabel f
'''


def test_the_callee_gets_the_callers_pointer_in_every_call_and_in_its_prototype():
    [(family, text)] = variants(DRAFT, 'f', ASM, 'mips', '')
    assert family == FAMILY
    assert 's32 g2(void *, s32);' in text
    assert text.count('g2(arg0, v);') == 2
    assert 'g1();' in text


def test_an_argument_the_target_writes_is_not_passed_on():
    asm = ASM.replace('addiu      $a1, $zero, 0x12C', 'addiu      $a0, $zero, 0x12C')
    assert variants(DRAFT, 'f', asm, 'mips', '') == []


def test_the_project_header_prototype_blocks_it():
    assert variants(DRAFT, 'f', ASM, 'mips', 's32 g2(s32);') == []


def test_a_call_with_the_wrong_argument_count_is_left_alone():
    assert variants(DRAFT.replace('g2(v);\n        break', 'g2(v, v);\n        break'), 'f', ASM, 'mips', '') == []


def test_a_caller_that_writes_its_parameter_is_left_alone():
    assert variants(DRAFT.replace('v = 0x12C;', 'arg0 = 0; v = 0x12C;'), 'f', ASM, 'mips', '') == []


def test_the_family_declares_itself_to_the_registry():
    [repair] = [item for item in registry.declared() if FAMILY in item.families]
    assert registry.problems(repair) == []
