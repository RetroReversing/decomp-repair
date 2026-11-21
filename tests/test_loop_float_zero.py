import pytest

from decomprepair.float_zero_local_repairs import loop_variants

SOURCE = """void update(int count) {
    f32 point[3];
    do {
        { register f32 zero = 0.0f; point[2] = zero; point[1] = zero; point[0] = zero; }
        draw(point);
        point[2] = 0.0f; point[1] = 0.0f; point[0] = 0.0f;
        draw(point);
        if (count > 2) {
            point[2] = 0.0f; point[1] = 0.0f; point[0] = 0.0f;
            draw(point);
        }
    } while (--count);
}"""
STORES = 'swc1 $f20, 0x38($sp)\nswc1 $f20, 0x34($sp)\nswc1 $f20, 0x30($sp)\n'
ASM = 'mtc1 $zero, $f20\n' + STORES * 3


def test_reuses_one_float_zero_per_outer_loop_iteration():
    [(family, candidate)] = loop_variants(SOURCE, 'update', ASM)
    assert family == 'loop_float_zero'
    assert 'do {\n        f32 __repair_loop_fzero = 0.0f;' in candidate
    assert candidate.count('= __repair_loop_fzero;') == 9
    assert candidate.count('draw(point);') == 3


@pytest.mark.parametrize('source, asm', [
    (SOURCE.replace('f32 point[3]', 'volatile  f32 point[3]'), ASM),
    (SOURCE.replace('f32 point[3]', 'f32 *point'), ASM),
    (SOURCE.replace('point[1] = 0.0f;', 'point[1] = 1.0f;', 1), ASM),
    (SOURCE, ASM.replace('mtc1 $zero', 'mtc1 $v0')),
    (SOURCE, ASM.replace(STORES, '', 1)),
])
def test_requires_three_repeated_unqualified_float_clears(source, asm):
    assert loop_variants(source, 'update', asm) == []
