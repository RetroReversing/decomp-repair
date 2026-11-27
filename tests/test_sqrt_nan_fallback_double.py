"""sqrtf_nan_fallback's double form: m2c's `v = sqrt(a); if (v != v) { v = fallback(); }` is the builtin `sqrt`."""
from decomprepair import sqrtf_nan_fallback as nan

SOURCE = '''extern f64 D_80001000;

s32 f(s32 arg0) {
    f64 root;
    f64 scaled;
    s32 result;

    root = sqrt((f64) arg0);
    if (root != root) {
        root = func_80002000();
    }
    scaled = root * 4096.0;
    if (D_80001000 <= scaled) {
        result = (s32) (scaled - D_80001000) | 0x80000000;
    } else {
        result = (s32) scaled;
    }
    return result;
}
'''
ASM = '''glabel f
/* 0 80000000 */  sqrt.d     $fv1, $fa0
/* 4 80000004 */  c.eq.d     $fv1, $fv1
/* 8 80000008 */  bc1t       .L80000014
/* C 8000000C */  jal        func_80002000
.L80000014:
/* 10 80000010 */  jr         $ra
endlabel f
'''


def test_the_double_retry_block_is_dropped_and_sqrt_declared():
    out = dict(nan.variants(SOURCE, 'f', ASM))[nan.FAMILY]
    assert 'func_80002000' not in out and 'f64 sqrt(f64);\n' in out
    assert 'sqrt(f64)' not in dict(nan.variants(SOURCE, 'f', ASM, 'f64 sqrt(f64);\n'))[nan.FAMILY]


def test_a_double_retry_needs_the_double_root_in_the_target():
    assert nan.variants(SOURCE, 'f', ASM.replace('sqrt.d', 'sqrt.s')) == []
