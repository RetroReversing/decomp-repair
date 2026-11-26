"""A product by a constant wider than 32 bits with trailing zero bits: `e * (K << n)` as `(e * K) << n`."""
import pytest

from decomprepair import registry
from decomprepair.wide_constant_shift_split import FAMILY, variants

DRAFT = '''extern char D_801D9220[];

s32 f(s32 arg0) {
    return (s32) ((arg0 - (s32) &D_801D9220) * -0x22222222000) >> 0x10;
}
'''


def _kids(text, header=None):
    return [s for fam, s in variants(text, 'f', header) if fam == FAMILY]


def test_a_wide_negative_constant_becomes_a_narrow_product_and_a_shift():
    want = DRAFT.replace('((arg0 - (s32) &D_801D9220) * -0x22222222000)',
                         '(((arg0 - (s32) &D_801D9220) * -0x11111111) << 13)')
    assert want in _kids(DRAFT)


def test_a_smaller_shift_that_fits_in_32_bits_is_offered_too():
    kids = _kids(DRAFT)
    assert any('* -0x88888888) << 10)' in k for k in kids)


def test_the_literal_on_the_left_an_enclosing_group_and_no_shift_of_32():
    text = ('void f(s32 a, s32 *o) { o[0] = a * 17179869184; o[1] = 0x123457000000 * a; '
            'o[2] = (a * 0x123457000000); }\n')
    kids = _kids(text)
    assert not any('<< 32' in k for k in kids)   # a shift of 32 is undefined: never offered
    assert any('o[1] = ((a * 0x123457) << 24);' in k for k in kids)
    assert any('o[2] = ((a * 0x123457) << 24);' in k for k in kids)    # the group is reused, no second pair


def test_the_shifted_value_is_the_same_modulo_32_bits():
    for k in (-0x22222222000, 0x300000000, 0x7654311000):
        zeros = (abs(k) & -abs(k)).bit_length() - 1
        for a in (1, 5, 0x12345, 0x7FFFFFFF, -3):
            wide = (a * k) & 0xFFFFFFFF
            narrow = ((a * (k >> zeros)) << zeros) & 0xFFFFFFFF
            assert wide == narrow


def test_every_site_together_and_the_cap():
    text = 'void f(s32 a, s32 *o) { o[0] = a * 0x123457000000; o[1] = a * 0x765431000000; }\n'
    kids = _kids(text)
    assert any('o[0] = ((a * 0x123457) << 24);' in k and 'o[1] = ((a * 0x765431) << 24);' in k for k in kids)
    assert len(kids) <= 12


@pytest.mark.parametrize('text', [
    'void f(s32 a) { s32 t = a * 0x22222222; }',              # a 32-bit constant is not wide
    'void f(s32 a) { s32 t = a * 0x22222222001; }',           # no trailing zero bit
    'void f(s32 a) { s32 t = g(a) * 0x22222222000; }',        # a call is not moved
    'void f(s32 *p) { s32 t = (*p++) * 0x22222222000; }',     # a side effect
    'void f(f32 x, f32 *o) { *o = x * 0x22222222000; }',      # float
    'void f(s32 a) { a *= 0x22222222000; }',                  # a compound assignment
])
def test_shapes_it_must_leave_alone(text):
    assert _kids(text) == []


def test_it_is_declared_for_the_registry():
    ours = [r for r in registry.declared() if FAMILY in r.families]
    assert len(ours) == 1 and registry.problems(ours[0]) == []
