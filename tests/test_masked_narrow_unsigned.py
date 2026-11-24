"""unsigned_narrow_local for a narrow local that only ever holds a mask past its sign bit (`s16 m = w & 0xFF00;`): a
KMC GCC 2.7.2 collision routine kept m2c's `s16`, and as a `u16` went 13655 -> 12757. The function sign-extends other
halfwords (`lh`), which used to keep the family from offering any `s16` local. The source below is made up."""
from decomprepair import leaf_frame_repairs

SOURCE = """extern s32 cells(void);
extern void use(u16, s16, s16);
void f(s16 *p) {
    s32 w;
    u16 lo;
    s16 hi;
    s16 n;
    w = cells();
    lo = w & 0xFF;
    hi = w & 0xFF00;
    n = *p;
    use(lo, hi, n);
}
"""
ASM = 'jal cells\nnop\nlh $a2, 0($s0)\nandi $a1, $v0, 0xff00\n'


def test_a_local_holding_a_mask_past_the_sign_bit_is_offered_unsigned():
    children = [text for family, text in leaf_frame_repairs.variants(SOURCE, 'f', ASM) if family == 'unsigned_narrow_local']
    assert len(children) == 1
    assert '    u16 hi;' in children[0] and '    s16 n;' in children[0]


def test_a_mask_inside_the_sign_range_or_another_assignment_keeps_it_signed():
    low = SOURCE.replace('w & 0xFF00', 'w & 0x7F00')
    assert not [t for f, t in leaf_frame_repairs.variants(low, 'f', ASM) if f == 'unsigned_narrow_local']
    other = SOURCE.replace('    n = *p;', '    n = *p;\n    hi = n;')
    assert not [t for f, t in leaf_frame_repairs.variants(other, 'f', ASM) if f == 'unsigned_narrow_local']
