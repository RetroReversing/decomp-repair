"""A volatile scratch nothing names is removed as one candidate."""
from decomprepair import frame_padding_repairs as f

SOURCE = '''void g(s32 x)
{
  u8 buffer[16];
  volatile unsigned short pad;
  s32 i;
  for (i = 0; i < x; i++)
  {
    buffer[i] = 0;
  }
}
'''


def test_the_unreferenced_scratch_is_dropped():
    (family, text), = f.drop_variants(SOURCE, 'g')
    assert family == 'unused_frame_padding_drop' and 'pad' not in text and 'buffer[16]' in text
    assert f.DROP_FAMILY in f.FAMILIES


def test_a_scratch_the_function_uses_stays():
    assert f.drop_variants(SOURCE.replace('s32 i;', 's32 i;\n  pad = 1;'), 'g') == []
