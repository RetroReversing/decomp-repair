import pytest

from decomprepair.float_matrix_identity import applies, rewrite

ASM = '''
glabel fill
move $a2, $zero
lui $at, 0x3f80
mtc1 $at, $f0
move $a3, $a0
.Lrow:
move $v1, $zero
move $a1, $a0
.Lcol:
bnel $a2, $v1, .Lstep
sw $zero, ($a1)
swc1 $f0, ($a3)
.Lstep:
addiu $v1, $v1, 1
slti $v0, $v1, 4
bnez $v0, .Lcol
addiu $a1, $a1, 4
addiu $a3, $a3, 20
addiu $a2, $a2, 1
slti $v0, $a2, 4
bnez $v0, .Lrow
addiu $a0, $a0, 16
jr $ra
nop
endlabel fill
'''
DRAFT = '''
void fill(M2C_UNK32 *input) {
    M2C_UNK32 *base;
    M2C_UNK32 *cursor;
    M2C_UNK32 *diagonal;
    s32 row;
    s32 col;

    base = input;
    row = 0;
    diagonal = base;
    do {
        col = 0;
        cursor = base;
    walk:
        if (row != col) { *cursor = 0; } else { *diagonal = 0x3F800000; }
        col += 1;
        cursor += 4;
        if (col < 4) { goto walk; }
        diagonal += 0x14;
        row += 1;
        base += 0x10;
    } while (row < 4);
}
'''


@pytest.mark.parametrize('draft', [
    DRAFT,
    DRAFT.replace('row = 0;\n    diagonal = base;', 'diagonal = base;\n    row = 0;').replace(
        'if (row != col) { *cursor = 0; } else { *diagonal = 0x3F800000; }',
        'if (row == col) { *diagonal = 0x3F800000; } else { *cursor = 0; }'),
])
def test_recovers_word_steps_in_both_branch_orientations(draft):
    fixed = rewrite(draft, 'fill', ASM)

    assert fixed
    assert 'row = 0;\n    __repair_matrix_one = 1.0f;\n    diagonal = input;' in fixed
    assert '*(f32 *)diagonal = __repair_matrix_one;' in fixed
    assert '*cursor = 0;' in fixed
    assert 'cursor++;\n        } while (col < 4);' in fixed
    assert 'diagonal += 5;' in fixed
    assert 'input += 4;' in fixed
    assert 'goto' not in fixed
    assert rewrite(fixed, 'fill', ASM) is None


@pytest.mark.parametrize(('old', 'new'), [
    ('swc1 $f0', 'swc1 $f2'),
    ('bnel $a2, $v1, .Lstep', 'bne $a2, $v1, .Lstep'),
    ('bnez $v0, .Lcol', 'bnez $v0, .Lrow'),
    ('slti $v0, $a2, 4', 'slti $v0, $a2, 3'),
    ('addiu $a3, $a3, 20', 'addiu $a3, $a3, 16'),
])
def test_rejects_different_target_store_or_traversal(old, new):
    other = ASM.replace(old, new)
    assert not applies(other)
    assert rewrite(DRAFT, 'fill', other) is None


def test_rejects_extra_source_work_or_conflicting_name():
    assert rewrite(DRAFT.replace('col += 1;', 'log(col); col += 1;'), 'fill', ASM) is None
    assert rewrite(DRAFT, 'fill', ASM, '#define __repair_matrix_one another') is None
