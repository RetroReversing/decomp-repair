import pytest

from decomprepair import relocated_byte_table as repair

# Effective addresses 0x8001F120 and 0x80023840 exercise both signs of the LO16 immediate.
ASM = '''
/* 00 80001000 3C068002 */ lui $a2, %hi(storage + 0x20)
/* 04 80001004 24C6F120 */ addiu $a2, $a2, %lo(storage + (0x20 & 0xFFFF))
.Lrepeat:
divu $zero, $a0, $a1
bnez $a1, .Ldivide
nop
break 7
.Ldivide:
mflo $a0
mfhi $v1
/* 20 80001020 3C028002 */ lui $v0, %hi(table_slots + 0x40)
/* 24 80001024 8C423840 */ lw $v0, %lo(table_slots + 0x40)($v0)
addu $v0, $v0, $v1
lbu $v0, ($v0)
addiu $a2, $a2, -1
bnez $a0, .Lrepeat
sb $v0, ($a2)
jr $ra
move $v0, $a2
'''
DRAFT = '''
extern M2C_UNK storage;
extern M2C_UNK table_slots;
u8 *format(u32 arg0, u32 arg1) {
    u32 var_a0;
    u32 temp_hi;
    u8 *var_a2;
    var_a0 = arg0;
    var_a2 = &storage + 0x20;
    do {
        temp_hi = var_a0 % arg1;
        var_a0 = var_a0 / arg1;
        var_a2 -= 1;
        *var_a2 = *(M2C_FIELD(&table_slots, s32 *, 0x40) + temp_hi);
    } while (var_a0 != 0);
    return var_a2;
}
'''
ADDRESSES = {'storage': 0x8001F100, 'table_slots': 0x80023800,
             'D_8001F120': 0x8001F120, 'D_80023840': 0x80023840}


@pytest.mark.parametrize('draft', [
    DRAFT,
    DRAFT.replace('&storage + 0x20', '(void *)(&storage); var_a2 = (void *)((char *)var_a2 + (s32)(0x20))')
         .replace('= *(M2C_FIELD', '= *(s32 *)(M2C_FIELD'),
])
def test_recover_signed_relocation_and_unsigned_byte_lookup(draft):
    assert repair.applies(ASM)
    candidate = repair.rewrite(draft, 'format', ASM, resolve=ADDRESSES.get)
    assert 'extern u8 D_8001F120[];' in candidate
    assert 'extern u8 *D_80023840;' in candidate
    assert 'var_a2 = D_8001F120;' in candidate
    assert '*var_a2 = D_80023840[temp_hi];' in candidate
    assert 'temp_hi = var_a0 % arg1;' in candidate
    assert 'var_a2 -= 1;' in candidate


@pytest.mark.parametrize('asm', [
    ASM.replace('lbu $v0', 'lw $v0'),
    ASM.replace('mfhi $v1', 'mflo $v1'),
    ASM.replace('8C423840', '8C423841'),
    ASM.replace('%lo(table_slots + 0x40)', '%lo(storage + 0x40)'),
])
def test_requires_target_byte_lookup_and_matching_relocation_words(asm):
    assert repair.rewrite(DRAFT, 'format', asm, resolve=ADDRESSES.get) is None


def test_respects_reviewed_declarations_and_unverified_source_offsets():
    assert repair.rewrite(DRAFT, 'format', ASM, 'extern int D_80023840;', ADDRESSES.get) is None
    assert repair.rewrite(DRAFT.replace('+ 0x20', '+ 0x24'), 'format', ASM, resolve=ADDRESSES.get) is None
