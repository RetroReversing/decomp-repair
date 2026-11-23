"""A local's last use, shifted, written as the shift in place."""
from decomprepair.last_use_shift_in_place import FAMILY, variants

# A canonical-code lookup in a bit-stream decoder (KMC GCC 2.7.2, N64): the peeked window `x` is read for the first
# level and, shifted, for the second; the next pass of the loop sets it afresh.
LOOKUP = '''void f(u16 *t, u32 *in, u32 n)
{
  u32 x;
  u32 y;
  do {
    x = *in++;
    y = t[x & 0x3FF];
    if ((y & 15) == 0) {
      y = t[(y >> 7) + ((x >> 10) & 7)];
    }
    t[0] = y;
  } while (--n != 0);
}
'''


def _children(text):
    return [src for fam, src in variants(text, 'f') if fam == FAMILY]


def test_the_windows_last_shift_is_written_in_place():
    assert _children(LOOKUP) == [LOOKUP.replace('((x >> 10) & 7)', '((x >>= 10) & 7)')]


def test_a_value_read_again_later_is_left_alone():
    assert _children(LOOKUP.replace('t[0] = y;', 't[0] = y + x;')) == []


def test_a_loop_that_reads_the_value_before_setting_it_is_left_alone():
    text = LOOKUP.replace('    x = *in++;\n    y = t[x & 0x3FF];', '    y = t[x & 0x3FF];\n    x = *in++;')
    assert _children(text) == []


def test_a_value_a_macro_may_read_is_left_alone():
    assert _children('#define PEEK(d) d = x\n' + LOOKUP) == []
