from decomprepair import registry
from decomprepair.stripped_call_arguments import variants

ASM = '''glabel func_80001000
/* 0 */  addiu $sp, $sp, -0x18
/* 4 */  sw $s0, 0x10($sp)
/* 8 */  addu $s0, $a0, $zero
/* C */  sw $ra, 0x14($sp)
/* 10 */ addiu $v0, $zero, 0x50
/* 14 */ lui $a1, %hi(D_80008000)
/* 18 */ addu $a0, $s0, $zero
/* 1C */ addiu $a1, $a1, %lo(D_80008000)
/* 20 */ jal func_80002000
/* 24 */ sh $v0, 0x2($s0)
/* 28 */ lw $ra, 0x14($sp)
/* 2C */ lw $s0, 0x10($sp)
/* 30 */ jr $ra
/* 34 */ addiu $sp, $sp, 0x18
'''

SOURCE = '''void func_80002000(void); /* matched callee */

void func_80001000(void *arg0) {
    M2C_FIELD(arg0, u16 *, 2) = 0x50;
    func_80002000();
}
'''


def test_the_loaded_arguments_are_written_into_the_empty_call():
    [(family, child)] = variants(SOURCE, 'func_80001000', ASM, 'mips')
    assert family == 'stripped_call_arguments'
    assert 'func_80002000(arg0, D_80008000);' in child
    assert 'void func_80002000(); /* matched callee */' in child
    assert 'extern u8 D_80008000[];' in child


def test_a_declared_scalar_symbol_is_passed_by_address():
    [(_, child)] = variants('extern s32 D_80008000;\n' + SOURCE, 'func_80001000', ASM, 'mips')
    assert 'func_80002000(arg0, &D_80008000);' in child
    assert 'extern u8' not in child


def test_a_constant_and_a_zero():
    asm = ASM.replace('lui $a1, %hi(D_80008000)', 'addu $a1, $zero, $zero').replace(
        'addiu $a1, $a1, %lo(D_80008000)', 'addiu $a2, $zero, 0x7')
    [(_, child)] = variants(SOURCE, 'func_80001000', asm, 'mips')
    assert 'func_80002000(arg0, 0, 0x7);' in child


def test_nothing_without_the_first_argument_register_or_with_arguments_already():
    assert variants(SOURCE, 'func_80001000', ASM.replace('addu $a0, $s0, $zero', 'nop'), 'mips') == []
    assert variants(SOURCE.replace('func_80002000();', 'func_80002000(arg0);'), 'func_80001000', ASM, 'mips') == []
    assert variants(SOURCE, 'func_80001000', ASM, 'ppc') == []


def test_a_load_from_before_a_branch_is_not_the_calls():
    asm = ASM.replace('addu $a0, $s0, $zero', 'nop').replace('addiu $v0, $zero, 0x50',
                                                          'addu $a0, $s0, $zero\n/* x */ beqz $v0, .L1\n nop')
    assert variants(SOURCE, 'func_80001000', asm, 'mips') == []


def test_it_is_registered():
    assert 'stripped_call_arguments' in [family for repair in registry.declared() for family in repair.families]
