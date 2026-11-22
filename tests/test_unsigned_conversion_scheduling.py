from decomprepair.unsigned_conversion_repairs import SCHEDULING, variants

SOURCE = """void f(float a, float b) {
    if (a >= 2.1474836e9f) {
        x = (s32) (a - 2.1474836e9f);
        x = x | 0x80000000;
    } else {
        x = (s32) a;
    }
    if (!(b >= 2.1474836e9f)) {
        y = (s32) b;
    } else {
        y = (s32) (b - 2.1474836e9f);
        y = y | 0x80000000;
    }
}"""


def test_offers_branch_swap_and_later_high_bit_store_together():
    candidates = [text for family, text in variants(SOURCE, 'f') if family == SCHEDULING]
    assert 'if (!(a >= 2.1474836e9f))' in candidates[0]
    assert 'do { y = y | 0x80000000; } while (0);' in candidates[0]
    assert candidates[0].index('x = (s32) a;') < candidates[0].index('x = (s32) (a -')


def test_rejects_a_different_high_bit_expression():
    source = SOURCE.replace('y | 0x80000000', 'y | 0x40000000')
    assert not any('do {' in text for family, text in variants(source, 'f') if family == SCHEDULING)
