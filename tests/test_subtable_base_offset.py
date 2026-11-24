"""A two-level table's second lookup with the entry's offset in the pointer."""
from decomprepair.subtable_base_offset import FAMILY, variants

# A canonical-code lookup (KMC GCC 2.7.2, N64): the first level by the window's low bits, the second by the entry's
# subtable offset plus the window's next bits; the window is set afresh on the next pass.
LOOKUP = '''void f(u16 *t, u32 *in, u32 n)
{
  u32 x;
  u32 c;
  do {
    x = *in++;
    c = D_801032B0[x & 0x3FF];
    if ((c & 15) == 0) {
      c = (D_801032B0 + 0x400)[(c >> 7) + ((x >>= 10) & ((1 << ((c >> 4) & 7)) - 1))];
    }
    t[0] = c;
  } while (--n != 0);
}
'''


def _children(text):
    return [src for fam, src in variants(text, 'f') if fam == FAMILY]


def test_the_offset_moves_into_the_pointer_with_and_without_the_shift_in_place():
    kids = _children(LOOKUP)
    old = '(D_801032B0 + 0x400)[(c >> 7) + ((x >>= 10) & ((1 << ((c >> 4) & 7)) - 1))]'
    assert LOOKUP.replace(old, '(D_801032B0 + 0x400 + (c >> 7))[(x >>= 10) & ((1 << ((c >> 4) & 7)) - 1)]') in kids
    assert LOOKUP.replace(old, '(D_801032B0 + 0x400 + (c >> 7))[(x >> 10) & ((1 << ((c >> 4) & 7)) - 1)]') in kids
    assert len(kids) == 2


def test_a_window_read_again_keeps_its_shift_in_place():
    kids = _children(LOOKUP.replace('t[0] = c;', 't[0] = c + x;'))
    assert len(kids) == 1 and '(x >>= 10)' in kids[0]


def test_both_lookups_are_offered_together():
    text = LOOKUP.replace('    t[0] = c;', '    t[1] = (D_80108970 + 0x100)[(c >> 7) + ((x >> 8) & 3)];\n    t[0] = c;')
    kids = _children(text)
    assert any('(D_80108970 + 0x100 + (c >> 7))[(x >> 8) & 3]' in k and '(D_801032B0 + 0x400 + (c >> 7))' in k for k in kids)


def test_an_index_that_is_not_a_sum_is_left_alone():
    assert _children(LOOKUP.replace('[(c >> 7) + ((x >>= 10) & ((1 << ((c >> 4) & 7)) - 1))]', '[(c >> 7)]')) == []


def test_volatile_declines():
    assert _children(LOOKUP.replace('  u32 c;', '  volatile u32 c;')) == []
