import pytest

from decomprepair.field_snapshot_copies import rewrite

ASM = '''
glabel copy_fields
lui $v0, %hi(state + 0x20)
lw $v0, %lo(state + 32)($v0)
lhu $v1, 0x4($v0)
lhu $a0, 0x6($v0)
lhu $v0, 0x8($v0)
lui $at, %hi(dest + 0x8000)
sh $v1, %lo(dest + (0x8000 & 0xFFFF))($at)
lui $at, %hi(state + 0x16)
sh $a0, %lo(state + 22)($at)
lui $at, %hi(last)
jr $ra
sh $v0, %lo(last)($at)
endlabel copy_fields
'''

DRAFT = '''
void copy_fields(void) {
    M2C_FIELD(&state, u16 *, 0x16) = M2C_FIELD(M2C_FIELD(&state, void **, 0x20), u16 *, 6);
    M2C_FIELD(&dest, u16 *, 0x8000) = (u16) M2C_FIELD(M2C_FIELD(&state, void **, 0x20), u16 *, 4);
    M2C_FIELD(&last, u16 *, 0) = M2C_FIELD(M2C_FIELD(&state, void **, 0x20), u16 *, 8);
}
'''


def test_snapshots_precede_stores_in_target_order():
    fixed = rewrite(DRAFT, 'copy_fields', ASM)
    assert fixed
    assert fixed.splitlines()[6:] == [
        '    __repair_field_snapshot0 = (u16) M2C_FIELD(M2C_FIELD(&state, void **, 0x20), u16 *, 4);',
        '    __repair_field_snapshot1 = M2C_FIELD(M2C_FIELD(&state, void **, 0x20), u16 *, 6);',
        '    __repair_field_snapshot2 = M2C_FIELD(M2C_FIELD(&state, void **, 0x20), u16 *, 8);',
        '    M2C_FIELD(&dest, u16 *, 0x8000) = __repair_field_snapshot0;',
        '    M2C_FIELD(&state, u16 *, 0x16) = __repair_field_snapshot1;',
        '    M2C_FIELD(&last, u16 *, 0) = __repair_field_snapshot2;',
        '}',
    ]


@pytest.mark.parametrize(('old', 'new'), [
    ('lhu $v1', 'lh $v1'),
    ('lhu $v1, 0x4($v0)', 'lhu $v0, 0x4($v0)'),
    ('sh $v1', 'sh $a0'),
    ('%lo(state + 22)', '%lo(state + 23)'),
    ('%lo(last)', '%lo(dest)'),
])
def test_rejects_unproved_memory_operands(old, new):
    assert rewrite(DRAFT, 'copy_fields', ASM.replace(old, new)) is None


@pytest.mark.parametrize(('old', 'new'), [
    ('void **, 0x20', 'void **, 0x24'),
    ('u16 *, 4);', 'u16 *, 6);'),
    ('u16 *, 8);', 'u16 *, 8);\n    notify();'),
])
def test_requires_same_input_offsets_and_destinations(old, new):
    assert rewrite(DRAFT.replace(old, new), 'copy_fields', ASM) is None


def test_word_loads_can_be_interleaved_with_relocated_stores():
    asm = '''
    lw $v0, 4($a0)
    lw $v1, 8($a0)
    lui $at, %hi(out)
    sw $v0, %lo(out)($at)
    lw $v0, 12($a0)
    lui $at, %hi(out + 4)
    sw $v1, %lo(out + 4)($at)
    lui $at, %hi(out + 8)
    jr $ra
    sw $v0, %lo(out + 8)($at)
    '''
    source = '''
    void copy_words(void *in) {
        M2C_FIELD(&out, s32 *, 0) = M2C_FIELD(in, s32 *, 4);
        M2C_FIELD(&out, s32 *, 4) = M2C_FIELD(in, s32 *, 8);
        M2C_FIELD(&out, s32 *, 8) = M2C_FIELD(in, s32 *, 12);
    }
    '''
    fixed = rewrite(source, 'copy_words', asm)
    assert fixed
    assert fixed.index('M2C_FIELD(&out, s32 *, 0) =') < fixed.index('M2C_FIELD(in, s32 *, 12)')
    assert rewrite(source, 'copy_words', asm.replace('lw $v1, 8', 'lw $v0, 8')) is None
