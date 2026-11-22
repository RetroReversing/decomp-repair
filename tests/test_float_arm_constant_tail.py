"""A float constant each arm sets, multiplied after the join, goes into each arm."""
from decomprepair import float_arm_constant_tail as tail

SOURCE = '''extern f32 table[];
f32 f(s32 flags, s32 n) {
    f32 scale;
    s32 idx;
    f32 result;

    if (flags & 0x20000000) {
        scale = 0.75f;
        idx = n * 4;
    } else {
        scale = 0.25f;
        idx = n * 4;
    }
    result = scale * *((f32 *)((s8 *)&table + idx));
    return result;
}
'''


def test_the_product_goes_into_each_arm_after_its_other_statements():
    # A KMC GCC 2.7.2 N64 function: 15 ($f0/$f2 traded places) -> 0.
    (family, out), = tail.variants(SOURCE, 'f')
    assert family == 'float_arm_constant_tail'
    assert '''    if (flags & 0x20000000) {
        idx = n * 4;
        result = 0.75f * *((f32 *)((s8 *)&table + idx));
    } else {
        idx = n * 4;
        result = 0.25f * *((f32 *)((s8 *)&table + idx));
    }
    return result;''' in out
    assert 'scale =' not in out and '    f32 scale;\n' in out


def test_left_alone_when_the_variable_or_the_arms_do_more():
    assert not tail.variants(SOURCE.replace('return result;', 'return result + scale;'), 'f')  # read after the join
    assert not tail.variants(SOURCE.replace('scale = 0.25f;', 'scale = n;'), 'f')  # not a literal
    assert not tail.variants(SOURCE.replace('idx = n * 4;\n    }\n    result', 'return 0;\n    }\n    result'), 'f')
    assert not tail.variants(SOURCE.replace('    f32 scale;', '    s32 scale;'), 'f')
    assert not tail.variants(SOURCE.replace('    f32 scale;', '    volatile f32 scale;'), 'f')
    assert not tail.variants(SOURCE.replace('scale * *', 'scale * scale * *'), 'f')  # two uses
