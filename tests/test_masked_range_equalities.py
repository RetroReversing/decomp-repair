"""A byte's range test plus a masked equality, written out as the masked chain on an unsigned local."""
from decomprepair import masked_range_equalities as chain

SOURCE = '''s32 f(void *p) {
    s8 t;
    s32 r;

    t = M2C_FIELD(p, u8 *, 0x82);
    if (((u32) (t - 9) < 2U) || ((t & 0xFF) == 0xB)) {
        r = 1;
    } else {
        r = 0;
    }
    return r;
}
'''


def test_the_range_becomes_masked_equalities_on_an_unsigned_local():
    # A KMC GCC 2.7.2 N64 function: an lb and a missing andi (215) -> 15; with the float constants moved, exact.
    (family, out), = chain.variants(SOURCE, 'f')
    assert family == 'masked_range_equality_chain'
    assert '    u8 t;\n' in out
    assert 'if (((t & 0xFF) == 9) || ((t & 0xFF) == 0xA) || ((t & 0xFF) == 0xB)) {' in out
    assert chain.variants(out, 'f') == []  # no range left to unroll


def test_left_alone_without_the_masked_equality_or_for_a_wide_range():
    assert not chain.variants(SOURCE.replace(' || ((t & 0xFF) == 0xB)', ''), 'f')
    assert not chain.variants(SOURCE.replace('- 9) < 2U', '- 9) < 9U'), 'f')
    assert not chain.variants(SOURCE.replace('(t - 9)', '(t - 127)').replace('< 2U', '< 3U'), 'f')
