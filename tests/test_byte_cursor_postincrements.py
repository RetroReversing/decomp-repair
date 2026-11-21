import pytest

from decomprepair import byte_cursor_postincrements as repair

ASM = '''
lw $t1, 12($a0)
addiu $v0, $t1, 1
sw $v0, 12($a0)
lbu $v0, 0($t1)
addiu $t0, $t1, 2
sw $t0, 12($a0)
lbu $a2, 1($t1)
addiu $t0, $t1, 3
sw $t0, 12($a0)
lbu $a3, 2($t1)
addiu $t0, $t1, 4
sw $t0, 12($a0)
lbu $t0, 3($t1)
sll $v0, $v0, 24
sll $a2, $a2, 16
or $v0, $v0, $a2
sll $a3, $a3, 8
or $v0, $v0, $a3
jr $ra
or $v0, $v0, $t0
'''
DRAFT = '''
s32 next_word(void *owner) {
    void *snapshot;
    snapshot = M2C_FIELD(owner, void **, 12);
    M2C_FIELD(owner, void **, 12) = (void *) (snapshot + 1);
    M2C_FIELD(owner, void **, 12) = (void *) (snapshot + 2);
    M2C_FIELD(owner, void **, 12) = (void *) (snapshot + 3);
    M2C_FIELD(owner, void **, 12) = (void *) (snapshot + 4);
    return (M2C_FIELD(snapshot, u8 *, 0) << 24) | (M2C_FIELD(snapshot, u8 *, 1) << 16)
        | (M2C_FIELD(snapshot, u8 *, 2) << 8) | M2C_FIELD(snapshot, u8 *, 3);
}
'''


def test_preserves_each_advance_and_packs_unsigned_bytes():
    assert repair.applies(ASM)
    text = repair.rewrite(DRAFT, 'next_word', ASM)
    assert text.count('= *(M2C_FIELD(owner, u8 **, 12))++;') == 4
    assert 'u8 __repair_cursor_byte0, __repair_cursor_byte1;' in text
    assert 'return ((u32)__repair_cursor_byte0 << 24) | (__repair_cursor_byte1 << 16)' in text


@pytest.mark.parametrize('asm', [
    ASM.replace('sw $t0, 12($a0)', 'sw $t0, 16($a0)', 1),
    ASM.replace('lbu $a3, 2($t1)', 'lbu $a3, 1($t1)'),
    ASM.replace('sll $a2, $a2, 16', 'sll $a2, $a2, 8'),
    ASM.replace('lbu $a2, 1($t1)', 'lbu $v0, 1($t1)'),
])
def test_rejects_different_slots_packing_and_overwritten_values(asm):
    assert repair.rewrite(DRAFT, 'next_word', asm) is None


def test_rejects_changed_cursor_arithmetic_and_conflicting_macro():
    assert repair.rewrite(DRAFT.replace('snapshot + 2', 'snapshot + 4'), 'next_word', ASM) is None
    assert repair.rewrite(DRAFT, 'next_word', ASM, '#define __repair_cursor_byte0 something') is None
