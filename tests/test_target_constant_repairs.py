"""A borrowed twin's constants replaced with the target's immediates."""
from decomprepair import target_constant_repairs as t

SOURCE = '''void f(void) {
    u32 i;
    s32 off;

    D = g(0x3C00, 0xC);
    memset(D, 0, 0xF00);
    i = 0;
    off = 0;
    do {
        h(D + off);
        i += 1;
        off += 0x3C;
    } while (i < 0x40U);
}
'''
ASM = '''addiu      $sp, $sp, -0x20
addiu      $a0, $zero, 0x2C00
addiu      $a1, $zero, 0xD
addiu      $a2, $zero, 0x1640
addiu      $s1, $s1, 0x1
sltiu      $v0, $s1, 0xC0
addiu      $s0, $s0, 0x2C
addiu      $sp, $sp, 0x20
'''


def test_pairs_by_order_and_by_size():
    # An N64 function borrowed its sibling's C: 98.7%; exact with the sizes paired smallest with smallest (its loop's
    # step and bound are scheduled the other way round, so in order of appearance two of them were swapped).
    (_, ordered), (family, ranked) = t.variants(SOURCE, 'f', ASM)
    assert family == 'target_constant'
    assert 'g(0x2C00, 0xD);' in ranked and 'memset(D, 0, 0x1640);' in ranked
    assert 'off += 0x2C;' in ranked and 'i < 0xC0U' in ranked
    assert 'off += 0xC0;' in ordered


def test_left_alone_when_the_counts_differ_or_nothing_is_missing():
    assert t.variants(SOURCE, 'f', ASM.replace('addiu      $a1, $zero, 0xD\n', '')) == []
    same = SOURCE.replace('0x3C00, 0xC', '0x2C00, 0xD').replace('0xF00', '0x1640').replace('0x3C;', '0x2C;') \
        .replace('0x40U', '0xC0U')
    assert t.variants(same, 'f', ASM) == []
    assert t.variants(SOURCE, 'f', '') == []
