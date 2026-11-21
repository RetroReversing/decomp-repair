import pytest

from decomprepair.load_store_order_repairs import COMPONENT_BEFORE_RESETS, component_before_resets

SOURCE = """typedef struct { f32 v[3]; } Vector;
extern void *first;
extern void **second;
void update(Vector *input) {
    Vector output;
    output.v[1] = 0.0f;
    first = NULL;
    second = NULL;
    output.v[2] = M2C_FIELD(input, f32 *, 8);
    consume(&output);
}"""
ASM = """lwc1 $f0, 0x8($a0)
lui $at, %hi(first)
sw $zero, %lo(first)($at)
lui $at, %hi(second)
sw $zero, %lo(second)($at)
beqz $s1, .Lexit
swc1 $f0, 0x30($sp)"""


def test_move_component_before_resets():
    [(family, candidate)] = component_before_resets(SOURCE, 'update', ASM)
    assert family == COMPONENT_BEFORE_RESETS
    assert candidate.index('output.v[2]') < candidate.index('first = NULL') < candidate.index('second = NULL')


@pytest.mark.parametrize('source,asm', [
    (SOURCE.replace('extern void *first;', 'extern s32 first;'), ASM),
    (SOURCE.replace('Vector output;', 'Vector *output;'), ASM),
    (SOURCE.replace('f32 *, 8', 'volatile f32 *, 8'), ASM),
    (SOURCE, ASM.replace('%lo(second)', '%lo(other)')),
    (SOURCE, ASM.replace('swc1 $f0', 'swc1 $f2')),
])
def test_requires_an_independent_local_vector_load_and_two_target_resets(source, asm):
    assert component_before_resets(source, 'update', asm) == []
