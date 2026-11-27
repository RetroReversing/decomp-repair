from decomprepair import registry
from decomprepair import shifted_dividend_remainder as repair

DRAFT = '''void func_tick(void *arg0) {
    s32 temp_a1;
    s32 temp_v0;

    temp_v0 = (*(s32 *)((s8 *)(arg0) + 0x38));
    temp_a1 = temp_v0 + 1;
    (*(s8 *)((s8 *)(arg0) + 0x77)) = (s8) (((s32) (*(s32 *)((s8 *)(arg0) + 0x34)) >> 1) - (((*(s32 *)((s8 *)(arg0) + 0x34)) / 10) * 5));
    (*(u16 *)((s8 *)(arg0) + 0x6A)) = (u16) ((*(u16 *)((s8 *)(arg0) + 0x42)) + ((temp_a1 >> 1) - (((temp_v0 + 1) / 14) * 7)));
}
'''


def children(source):
    return [child for _, child in repair.variants(source, 'func_tick')]


def test_every_site_at_once_then_each_alone():
    both, first, second = children(DRAFT)
    assert '>> 1) % 5' in both and '(temp_a1 >> 1) % 7' in both
    assert '/ 10' not in both and '/ 14' not in both
    assert '% 5' in first and '/ 14' in first
    assert '% 7' in second and '/ 10' in second


def test_quotient_and_product_in_locals():
    source = '''void func_tick(s32 x, s32 *out) {
    s32 q;
    s32 p;
    s32 half;

    half = x >> 2;
    q = x / 12;
    p = q * 3;
    *out = half - p;
}
'''
    (child,) = children(source)
    assert '*out = half % 3;' in child


def test_refusals():
    for line in ('*out = (x >> 1) - ((x / 12) * 5);',     # not the shifted divisor
                 '*out = (x >> 1) - ((y / 10) * 5);',     # another value
                 '*out = (x >> 1) - ((x / 8) * 4);',      # a power of two
                 '*out = (x >> 1) - ((x / 10) * 5) + 1;'  # not the whole expression
                 ):
        source = 'void func_tick(s32 x, s32 y, s32 *out) {\n    %s\n}\n' % line
        assert children(source) == [], line


def test_declared_to_the_registry():
    assert repair.FAMILY in {family for entry in registry.declared() for family in entry.families}
