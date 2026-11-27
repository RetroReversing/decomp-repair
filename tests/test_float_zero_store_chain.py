from decomprepair import float_zero_store_chain as repair

SOURCE = '''void f(char *p) {
    M2C_FIELD(p, f32 *, 0x85c) = 0.0f;
    M2C_FIELD(p, f32 *, 0x858) = 0.0f;
    M2C_FIELD(p, f32 *, 0x854) = 0.0f;
}
'''
ASM = '''mtc1 $zero, $f0
nop
swc1 $f0, 0x85c($s3)
swc1 $f0, 0x858($s3)
swc1 $f0, 0x854($s3)
'''


def test_chain_zero_stores_in_original_order():
    out = repair.variants(SOURCE, 'f', ASM)
    assert len(out) == 1
    assert 'M2C_FIELD(p, f32 *, 0x854) = M2C_FIELD(p, f32 *, 0x858) = M2C_FIELD(p, f32 *, 0x85c) = 0.0f;' in out[0][1]


def test_requires_matching_float_zero_and_plain_distinct_fields():
    assert not repair.variants(SOURCE, 'f', ASM.replace('$zero', '$a0'))
    assert not repair.variants(SOURCE, 'f', ASM.replace('0x854', '0x850'))
    assert not repair.variants(SOURCE.replace('p, f32 *, 0x854', 'q, f32 *, 0x854'), 'f', ASM)
    assert not repair.variants(SOURCE.replace('0x854', '0x858'), 'f', ASM)
