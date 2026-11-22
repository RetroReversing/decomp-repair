from decomprepair.relocated_pointer_reloads import variants

SOURCE = '''
#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
extern M2C_UNK arena;
void f(void) {
    first(M2C_FIELD(M2C_FIELD(&arena, void **, 0x40), s32 *, 0x24));
    second(M2C_FIELD(M2C_FIELD(&arena, void **, 0x40), s32 *, 0x24));
}'''
ASM = '''
/* 00 80001000 3C028003 */ lui $v0, %hi(arena + 0x40)
/* 04 80001004 8C429120 */ lw $v0, %lo(arena + 0x40)($v0)
/* 08 80001008 0C000001 */ jal first
/* 0c 8000100c 00000000 */ nop
/* 10 80001010 3C028003 */ lui $v0, %hi(arena + 0x40)
/* 14 80001014 8C429120 */ lw $v0, %lo(arena + 0x40)($v0)
/* 18 80001018 0C000002 */ jal second
/* 1c 8000101c 00000000 */ nop
'''
ROWS = [
    ('o','lhu $a1, 0x7a($a0)',''),
    (' ','subu $v0, $v0, $v1','subu $v0, $v0, $v1'),
    (' ','sw $v0, %lo(total)($at)','sw $v0, %lo(total)($at)'),
    ('o','','lhu $a1, 0x7a($a0)'),
    ('r','lui $v0, %hi(alias)','lui $s0, %hi(alias)'),
    ('>','','addiu $s0, $s0, %lo(alias)'),
    ('i','lw $v0, %lo(alias)($v0)','lw $v0, ($s0)'),
    ('<','lui $v0, %hi(alias)',''),
    ('i','lw $v0, %lo(alias)($v0)','lw $v0, ($s0)'),
]
SYMBOLS = {'arena':0x800290e0, 'alias':0x80029120, 'D_80029120':0x80029120}


def test_direct_pointer_and_existing_field_view_candidate():
    result = dict(variants(SOURCE,'f','',ROWS,ASM,SYMBOLS.get))
    assert 'extern void *D_80029120;' in result['direct_pointer_reloads']
    assert result['direct_pointer_reloads'].count('M2C_FIELD(D_80029120, s32 *, 0x24)')==2
    assert '__typeof__' in result['direct_pointer_reloads_with_field_view']
    strict = dict(variants(SOURCE,'f','',ROWS,ASM,SYMBOLS.get,('-fstrict-aliasing',)))
    assert set(strict)=={'direct_pointer_reloads'}


def test_requires_both_relocations_and_field_addresses():
    assert not variants(SOURCE,'f','',ROWS,ASM.replace('8C429120','8C429124',1),SYMBOLS.get)
    assert not variants(SOURCE,'f','',ROWS[:-1],ASM,SYMBOLS.get)
    assert not variants(SOURCE.replace('0x40)','0x44)',1),'f','',ROWS,ASM,SYMBOLS.get)
    assert not variants(SOURCE,'f','#define arena other',ROWS,ASM,SYMBOLS.get)
