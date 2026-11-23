"""narrow_param_mask_cast: `id & 0xFFFF` on an `s16` parameter written as `(u16) id`.

Synthetic shape of a 795-instruction KMC object spawner (1245 -> 690): the mask read the extension cse had shared with the
table index, so combine could not fold the index's shifts, and the mask's register was the extension's."""
from decomprepair import narrow_param_mask_cast as s

SOURCE = '''void *spawn(s16 id, void *obj) {
  s32 k;
  put(obj, sTable[id]);
  k = id & 0xFFFF;
  look(k, id & 0xFF);
  return look(id & 0xFFFF);
}
'''


def _texts(source=SOURCE):
    return [text for family, text in s.variants(source, 'spawn') if family == s.FAMILY]


def test_the_halfword_masks_and_the_byte_masks_alone_and_together():
    texts = _texts()
    assert len(texts) == 3
    halves = [t for t in texts if '(u16) id' in t and '(u8) id' not in t]
    bytes_ = [t for t in texts if '(u8) id' in t and '(u16) id' not in t]
    both = [t for t in texts if '(u8) id' in t and '(u16) id' in t]
    assert len(halves) == len(bytes_) == len(both) == 1
    assert 'k = (u16) id;' in halves[0] and 'return look((u16) id);' in halves[0] and 'id & 0xFF)' in halves[0]
    assert 'look(k, (u8) id);' in bytes_[0]


def test_an_unsigned_or_wide_parameter_is_left_alone():
    assert _texts(SOURCE.replace('s16 id', 'u16 id')) == []
    assert _texts(SOURCE.replace('s16 id', 's32 id')) == []


def test_a_mask_of_another_variable_is_left_alone():
    source = SOURCE.replace('id & 0xFFFF', 'k & 0xFFFF').replace('id & 0xFF)', 'k & 0xFF)')
    assert _texts(source) == []
