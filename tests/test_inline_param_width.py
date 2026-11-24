"""An inline helper's integer parameter declared at another width."""
from decomprepair.inline_param_width import FAMILY, variants

SRC = '''static inline void branchAtLeast(void *voice, u32 value)
{
  if (value >= G)
  {
    jump(voice);
  }
}

void f(void *v)
{
  branchAtLeast(v, next() & 0xFF);
}
'''


def test_each_other_width_is_offered():
    kids = [src for fam, src in variants(SRC, 'f') if fam == FAMILY]
    assert len(kids) == 4
    assert SRC.replace('u32 value', 'u16 value') in kids and SRC.replace('u32 value', 'u8 value') in kids


def test_pointers_and_the_function_itself_are_left_alone():
    text = SRC.replace('u32 value', 'u8 *value')
    assert [src for fam, src in variants(text, 'f')] == []
    assert [src for fam, src in variants(SRC, 'branchAtLeast')] == []


def test_a_mask_parameter_is_not_narrowed_below_its_callers_constants():
    text = SRC.replace('branchAtLeast(v, next() & 0xFF);', 'branchAtLeast(v, 0x200000);')
    kids = [src for fam, src in variants(text, 'f') if fam == FAMILY]
    assert kids == [text.replace('u32 value', 's32 value')]


def test_a_mask_under_an_or_does_not_bound_the_value():
    text = SRC.replace('branchAtLeast(v, next() & 0xFF);', 'branchAtLeast(v, big() | next() & 0xFF);')
    kids = [src for fam, src in variants(text, 'f') if fam == FAMILY]
    assert kids == [text.replace('u32 value', 's32 value')]


PRED = '''static inline u8 owns(void *voice, s32 id)
{
  if (id != -1)
  {
    return 1;
  }
  return 0;
}

void f(void *v)
{
  if (owns(v, 3) & 0xFF)
  {
    act(v);
  }
}
'''


def test_a_predicates_return_type_is_offered_at_other_widths():
    kids = [src for fam, src in variants(PRED, 'f') if fam == FAMILY]
    assert PRED.replace('static inline u8 owns', 'static inline s32 owns') in kids


def test_a_return_of_a_wide_value_is_not_narrowed():
    text = PRED.replace('static inline u8 owns', 'static inline s32 owns').replace('return 1;', 'return id;')
    kids = [src for fam, src in variants(text, 'f') if fam == FAMILY]
    assert not any('static inline u8 owns' in k or 'static inline u16 owns' in k for k in kids)
