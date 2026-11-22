"""The four edits a key/velocity dispatch needed (500 -> 0 on a 231-instruction N64 function), and the chain of them."""
from decomprepair import narrow_param_clamp_repairs as narrow

SOURCE = '''static s32 lookup(s32 note, u8 bank)
{
  if (bank != 255)
  {
    return find(note & 0x7f, bank);
  }
  return -1;
}

s32 play(u32 packed, s32 note, s32 volume, u8 bank, s32 trim)
{
  u32 id = ((unsigned short) packed) >> 16;
  s32 level;
  s32 mix;
  level = trim + 1;
  switch (id & 0xc000)
  {
    case 0:
      return lookup(note, bank);
    case 0x4000:
      mix = table[note & 0xff] - 0x40;
      mix += volume & 0xff;
      if (mix < 0)
      {
        volume = 0;
      }
      else
        if (mix < 0x80)
      {
        volume = mix;
      }
      else
      {
        volume = 0x7f;
      }
      return emit(id, note & 0xff, note & 0x80, volume, level);
  }
  return -1;
}
'''


def families(source=SOURCE):
    return dict((family, text) for family, text in narrow.variants(source, 'play'))


def test_the_shift_of_a_halfword_cast_loses_the_cast():
    text = families()['halfword_shift_cast']
    assert 'u32 id = packed >> 16;' in text and '(unsigned short)' not in text


def test_a_word_local_of_the_high_half_becomes_a_halfword_once_the_cast_is_gone():
    assert 'u16 id = packed >> 16;' in families()['narrow_clamp_chain']
    assert 'u16 id' not in families()['halfword_shift_cast']
    assert 'u16 id' in families(SOURCE.replace('((unsigned short) packed)', 'packed'))['halfword_local_width']


def test_a_byte_masked_parameter_is_narrowed_with_the_helper_it_is_passed_to():
    kinds = [text for family, text in narrow.variants(SOURCE, 'play') if family == 'mask_parameter_narrow']
    assert len(kinds) == 2
    alone, with_helper = kinds
    assert 's32 play(u32 packed, u8 note,' in alone and 'lookup(s32 note,' in alone
    assert 'lookup(u8 note,' in with_helper
    assert 'note & 0xff' not in with_helper and 'note & 0x80' in with_helper and 'table[note]' in with_helper


def test_a_parameter_used_whole_or_assigned_is_not_narrowed():
    assert not [1 for family, _ in narrow.variants(SOURCE.replace('return -1;\n}\n', 'return note;\n}\n', 2), 'play')
                if family == 'mask_parameter_narrow']
    assert not [1 for family, _ in narrow.variants(SOURCE.replace('level = trim + 1;', 'note = 2; level = trim;'), 'play')
                if family == 'mask_parameter_narrow']


def test_the_range_test_is_computed_before_the_sign_test():
    text = families()['clamp_range_flag']
    assert 'mixInRange = mix < 0x80;' in text and 's32 mixInRange;' in text
    assert 'if (mix < 0) volume = 0; else if (!mixInRange) volume = 0x7f; else volume = mix;' in text


def test_the_chain_applies_every_step_as_one_child():
    text = families()['narrow_clamp_chain']
    assert 'u16 id = packed >> 16;' in text and 'u8 note' in text and 'lookup(u8 note,' in text
    assert 'mixInRange = mix < 0x80;' in text and '(unsigned short)' not in text


def test_nothing_is_offered_for_a_function_without_these_shapes():
    assert narrow.variants('s32 f(s32 a)\n{\n  return a + 1;\n}\n', 'f') == []
