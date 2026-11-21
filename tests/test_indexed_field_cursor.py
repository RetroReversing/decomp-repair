import pytest

from decomprepair import indexed_field_cursor as repair

ASM = '''
move $s4, $a0
move $s0, $zero
move $s2, $s4
.Litems:
sw $zero, 36($s2)
lw $v1, ($s4)
sll $v0, $s0, 2
addu $v0, $v0, $v1
lw $a0, ($v0)
sw $a0, 64($s2)
addiu $s0, $s0, 1
sltiu $v0, $s0, 8
bnez $v0, .Litems
addiu $s2, $s2, 4
jr $ra
nop
'''
DRAFT = '''
void init(void *obj, void *unused) {
    u32 i;
    s32 value;
    void *cursor;
    i = 0;
    cursor = obj;
    do {
        M2C_FIELD(cursor, s32 *, 36) = 0;
        value = *((i * 4) + M2C_FIELD(obj, void **, 0));
        M2C_FIELD(cursor, s32 *, 64) = value;
        i += 1;
        cursor += 4;
    } while (i < 8U);
}
'''


def test_index_both_fields_and_recover_table_load():
    candidate = repair.rewrite(DRAFT, 'init', ASM)
    assert 'void *cursor;' not in candidate
    assert 'M2C_FIELD(obj, s32 *, i * 4 + 36) = 0;' in candidate
    assert 'M2C_FIELD(obj, s32 *, i * 4 + 64) = value;' in candidate
    assert 'value = *(s32 *)((i * 4) + M2C_FIELD(obj, void **, 0));' in candidate
    assert candidate.count('i += 1;') == 1


@pytest.mark.parametrize(('source', 'asm'), [
    (DRAFT, ASM.replace('64($s2)', '68($s2)')),
    (DRAFT, ASM.replace('lw $a0, ($v0)', 'lbu $a0, ($v0)')),
    (DRAFT.replace('i += 1;', 'use(&(obj));\n        i += 1;'), ASM),
    (DRAFT.replace('i += 1;', 'use(cursor);\n        i += 1;'), ASM),
])
def test_rejects_changed_address_evidence_and_escaping_values(source, asm):
    assert repair.rewrite(source, 'init', asm) is None
