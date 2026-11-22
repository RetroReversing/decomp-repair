from decomprepair.measured_indirect_self_call import variants

SOURCE = '''
#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
extern M2C_UNK arena;
void f(void) {
    M2C_FIELD(&arena, M2C_UNK (**)(M2C_UNK), 0x40)(M2C_FIELD(&arena, M2C_UNK (**)(M2C_UNK), 0x40));
}'''
ASM = '''
/* 00 80001000 3C048003 */ lui $a0, %hi(arena + 0x40)
/* 04 80001004 8C849120 */ lw $a0, %lo(arena + 0x40)($a0)
/* 08 80001008 27BDFFE8 */ addiu $sp, $sp, -0x18
/* 0C 8000100C AFBF0010 */ sw $ra, 0x10($sp)
/* 10 80001010 0080F809 */ jalr $a0
/* 14 80001014 00000000 */ nop
'''
ROWS = [('|', 'nop', 'move $a0, $v1')]
SYMBOLS = {'arena': 0x800290E0}


def test_offer_void_callback_hypothesis_when_register_and_relocation_agree():
    result = variants(SOURCE,'f','',ROWS,ASM,SYMBOLS.get)
    assert len(result)==1
    assert 'M2C_FIELD(&arena, void (**)(void), 0x40)();' in result[0][1]


def test_requires_pointer_relocation_unchanged_argument_register_and_diff():
    assert not variants(SOURCE,'f','',[],ASM,SYMBOLS.get)
    assert not variants(SOURCE,'f','',ROWS,ASM.replace('8C849120','8C849124'),SYMBOLS.get)
    assert not variants(SOURCE,'f','',ROWS,ASM.replace('jalr $a0','jalr $v1'),SYMBOLS.get)
    assert not variants(SOURCE,'f','',ROWS,ASM.replace('sw $ra, 0x10($sp)','move $a0, $v0'),SYMBOLS.get)
    assert not variants(SOURCE.replace('0x40));','0x44));'),'f','',ROWS,ASM,SYMBOLS.get)
    assert not variants(SOURCE,'f','#define arena other',ROWS,ASM,SYMBOLS.get)
