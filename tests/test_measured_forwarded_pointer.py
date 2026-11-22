from decomprepair.measured_forwarded_pointer import variants

SOURCE = '''
M2C_UNK render(s32, s32, s32, s32, s32, s32, s32, s32, s32);
void f(void *obj, s32 mode) {
    s32 x;
    s32 y;
    x = (M2C_FIELD(obj, u16 *, 0x8A) * 2) & 0xFFFF;
    y = (M2C_FIELD(obj, u16 *, 0x88) * 2) & 0xFFFF;
    render(mode & 0xFFFF, x, y, x, 0, 0, 0, 0, y);
}'''
ASM = '''
addiu $sp, $sp, -0x30
sw $ra, 0x28($sp)
lhu $a2, 0x8A($a0)
lhu $a3, 0x88($a0)
andi $a1, $a1, 0xFFFF
sw $zero, 0x14($sp)
sw $zero, 0x18($sp)
sw $zero, 0x1c($sp)
sw $zero, 0x20($sp)
sll $a2, $a2, 1
andi $a2, $a2, 0xFFFF
sll $a3, $a3, 1
andi $a3, $a3, 0xFFFF
sw $a2, 0x10($sp)
jal render
sw $a3, 0x24($sp)
jr $ra
nop
'''


def test_offer_entry_pointer_and_update_the_inferred_prototype():
    result = variants(SOURCE,'f','',ASM)
    assert len(result)==1
    assert 'render(void *, s32, s32' in result[0][1]
    assert 'render(obj, mode & 0xFFFF,' in result[0][1]


def test_reject_unproven_pointer_or_call_shape():
    assert not variants(SOURCE,'f','',ASM.replace('lhu $a2, 0x8A($a0)','lw $a0, 0($a0)'))
    assert not variants(SOURCE,'f','',ASM.replace('sw $a3, 0x24($sp)','nop'))
    assert not variants(SOURCE,'f','',ASM.replace('andi $a1, $a1, 0xFFFF','andi $a1, $a1, 0xFF'))
    assert not variants(SOURCE,'f','#define obj other',ASM)
    assert not variants(SOURCE.replace('render(mode','obj = 0; render(mode'),'f','',ASM)
    assert not variants(SOURCE.replace('M2C_UNK render(s32','M2C_UNK render(u16',1),'f','',ASM)
