"""loop_index_cast_strip: narrowing casts on a short loop's counter as a subscript, dropped (630 -> 65 on a copy routine)."""
from decomprepair import loop_index_cast_strip as s

SOURCE = '''void copy(u16 *src) {
  s32 i;
  for (i = 0; i < 8; i++)
  {
    gText[(unsigned short) ((unsigned char) i)] = src[(unsigned char) i];
    if (src[i] == 0xFFFF)
    {
      break;
    }
  }
  for (i = 0; i < 4; i++) {
    gOther[(u16) i] = 0;
  }
}
'''


def _texts(source=SOURCE):
    return [text for family, text in s.variants(source, 'copy') if family == s.FAMILY]


def test_each_loop_and_both():
    texts = _texts()
    assert len(texts) == 3
    assert 'gText[i] = src[i];' in texts[0] and 'gOther[(u16) i]' in texts[0]
    assert 'gText[i] = src[i];' in texts[-1] and 'gOther[i] = 0;' in texts[-1]


def test_a_long_loop_or_a_changed_counter_is_left_alone():
    assert _texts(SOURCE.replace('i < 8', 'i < 300').replace('i < 4', 'i < 300')) == []
    assert _texts(SOURCE.replace('break;', 'i += 1;').replace('gOther[(u16) i] = 0;', 'gOther[(u16) i] = i++;')) == []


def test_a_cast_of_a_sum_is_kept():
    assert _texts(SOURCE.replace('(u16) i]', '(u16) (i + 1)]').replace('(unsigned short) ((unsigned char) i)', 'i').replace('(unsigned char) i', 'i')) == []
