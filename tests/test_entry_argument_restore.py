"""The parameter written back where the target passes it through (an SN gcc 2.8.1 actor update, 365 -> 210)."""
from decomprepair import registry
from decomprepair.entry_argument_restore import FAMILY, variants

DRAFT = '''s32 releaseEntity(u8);                 /* extern */
extern u8 *gOther;

void update(void *arg0_in) {
    void * arg0;
    s32 temp_a1_2;
    arg0 = arg0_in;
    temp_a1_2 = *gOther;
    if (temp_a1_2 == 0x80) {
        return;
    }
    releaseEntity(temp_a1_2);
}
'''

ASM = '''glabel update
addiu      $sp, $sp, -0x18
sw         $ra, 0x10($sp)
lui        $v1, %hi(gOther)
lw         $v1, %lo(gOther)($v1)
lbu        $a1, 0($v1)
addiu      $v0, $zero, 0x80
beq        $a1, $v0, .L1
nop
jal        releaseEntity
nop
.L1:
lw         $ra, 0x10($sp)
jr         $ra
addiu      $sp, $sp, 0x18
endlabel update
'''


def test_the_untouched_register_gets_the_parameter_and_the_prototype_takes_it():
    found = variants(DRAFT, 'update', asm=ASM, arch='mips')
    assert [family for family, _ in found] == [FAMILY]
    assert found[0][1] == DRAFT.replace('s32 releaseEntity(u8);', 's32 releaseEntity(void *);').replace(
        'releaseEntity(temp_a1_2);', 'releaseEntity(arg0_in);')


def test_a_register_the_target_writes_or_a_copy_of_the_parameter_is_left_alone():
    written = ASM.replace('jal        releaseEntity', 'move       $a0, $a1\njal        releaseEntity')
    assert variants(DRAFT, 'update', asm=written, arch='mips') == []
    assert variants(DRAFT.replace('releaseEntity(temp_a1_2);', 'releaseEntity(arg0);'), 'update', asm=ASM,
                    arch='mips') == []
    assert variants(DRAFT, 'update', asm=ASM, arch='ppc') == []


def test_it_is_registered():
    assert FAMILY in {family for entry in registry.declared() for family in entry.families}
