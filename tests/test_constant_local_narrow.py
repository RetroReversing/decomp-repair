"""constant_local_narrow, computed_compare_flip and compound_value_first: the three steps of a KMC -O1 easing routine."""
from decomprepair import computed_compare_flip as flip
from decomprepair import constant_local_narrow as narrow

SOURCE = '''void ease(s16 *p) {
  s32 v = 0;
  switch (mode) {
  case 1: v = 2; break;
  case 2: v = 0xA0; break;
  }
  p[4] += (s32) ((v - p[4]) / 8.0f);
  if (v - 2 < p[4] && p[4] < v + 2) { p[4] = v; }
}
'''


def _texts(module, family, source=SOURCE):
    return [text for found, text in module.variants(source, 'ease') if found == family]


def test_the_constant_local_is_narrowed_to_each_type_that_holds_it():
    texts = _texts(narrow, narrow.FAMILY)
    assert any('s16 v = 0;' in text for text in texts)
    assert any('u8 v = 0;' in text for text in texts)
    assert not any('s8 v = 0;' in text and 'u8 v' not in text for text in texts)


def test_a_local_that_holds_anything_else_is_left_alone():
    assert _texts(narrow, narrow.FAMILY, SOURCE.replace('v = 2;', 'v = mode;')) == []
    assert _texts(narrow, narrow.FAMILY, SOURCE.replace('v = 2;', 'v++;')) == []
    assert _texts(narrow, narrow.FAMILY, SOURCE.replace('v = 2;', 'use(&v);')) == []


def test_each_comparison_flipped_and_both():
    texts = _texts(flip, flip.COMPARE)
    assert len(texts) == 3
    assert any('if (p[4] > v - 2 && p[4] < v + 2)' in text for text in texts)


def test_the_added_value_comes_first():
    assert 'p[4] = (s32) ((v - p[4]) / 8.0f) + p[4];' in _texts(flip, flip.ADD)[0]


def test_a_call_in_the_added_value_is_left_alone():
    assert _texts(flip, flip.ADD, SOURCE.replace('(s32) ((v - p[4]) / 8.0f)', 'next()')) == []
