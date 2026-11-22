from decomprepair.measured_after_call_reload import variants

SOURCE = '''
#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
extern M2C_UNK arena;
void f(void) {
    M2C_FIELD(&arena, s32 *, 0x44) = (s32) M2C_FIELD(M2C_FIELD(&arena, void **, 0x40), s32 *, 4);
    unlink(M2C_FIELD(M2C_FIELD(&arena, void **, 0x40), s32 *, 4), M2C_FIELD(&arena, void **, 0x40));
}'''
ASM = '''
/* 00 80001000 3C058003 */ lui $a1, %hi(arena + 0x40)
/* 04 80001004 8CA59120 */ lw $a1, %lo(arena + 0x40)($a1)
/* 08 80001008 27BDFFE8 */ addiu $sp, $sp, -0x18
/* 0c 8000100c AFBF0010 */ sw $ra, 0x10($sp)
/* 10 80001010 0C000001 */ jal unlink
/* 14 80001014 8CA40004 */ lw $a0, 4($a1)
/* 18 80001018 3C028003 */ lui $v0, %hi(arena + 0x40)
/* 1c 8000101c 8C429120 */ lw $v0, %lo(arena + 0x40)($v0)
/* 20 80001020 8C420004 */ lw $v0, 4($v0)
/* 24 80001024 3C018003 */ lui $at, %hi(arena + 0x44)
/* 28 80001028 AC229124 */ sw $v0, %lo(arena + 0x44)($at)
/* 2c 8000102c 8FBF0010 */ lw $ra, 0x10($sp)
/* 30 80001030 03E00008 */ jr $ra
/* 34 80001034 27BD0018 */ addiu $sp, $sp, 0x18
'''
SYMBOLS = {'arena':0x800290e0,'D_80029120':0x80029120}


def test_recover_call_then_reload_with_verified_alias():
    result = variants(SOURCE,'f','',ASM,SYMBOLS.get)
    assert len(result)==1
    fixed=result[0][1]
    assert 'extern void *D_80029120;' in fixed
    assert fixed.index('    unlink(') < fixed.index('    M2C_FIELD(&arena, s32 *, 0x44) =')
    assert fixed.count('M2C_FIELD(D_80029120, s32 *, 4)')==2


def test_requires_matching_raw_relocations_and_source():
    assert not variants(SOURCE,'f','',ASM.replace('8C429120','8C429124'),SYMBOLS.get)
    assert not variants(SOURCE,'f','',ASM.replace('AC229124','AC229128'),SYMBOLS.get)
    assert not variants(SOURCE.replace('0x44)', '0x48)'), 'f','',ASM,SYMBOLS.get)
    assert not variants(SOURCE,'f','#define arena other',ASM,SYMBOLS.get)
    assert not variants(SOURCE,'f','',ASM,{'arena':0x800290e0}.get)
    assert not variants(SOURCE,'f','',ASM.replace('jal unlink','jal other'),SYMBOLS.get)
