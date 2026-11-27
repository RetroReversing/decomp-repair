from decomprepair import float_field_multiply_stage as repair

HEADER = '#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))'
ASM = 'lwc1 $f0, 4($a0)\nmul.s $f0, $f0, $f2\n'
SOURCE = '''void f(char *p, int flag) {
    f32 x;
    if (flag) {
        M2C_FIELD(p, f32 *, 8) = M2C_FIELD(p, f32 *, 4) * x * 0.35f;
    } else {
        M2C_FIELD(p, f32 *, 8) = M2C_FIELD(p, f32 *, 4) * x * 0.5f;
    }
}
'''


def test_stages_each_field_and_the_matching_pair():
    out = repair.variants(SOURCE, 'f', ASM, HEADER)
    assert len(out) == 3
    assert out[-1][1].count('repair_float_field = M2C_FIELD(p, f32 *, 4)') == 2


def test_requires_known_nonvolatile_float_and_target_load():
    assert not repair.variants(SOURCE, 'f', ASM)
    assert not repair.variants(SOURCE, 'f', 'nop', HEADER)
    assert not repair.variants(SOURCE, 'f', ASM, HEADER + '\ntypedef volatile float f32;')
