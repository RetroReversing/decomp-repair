"""call_first_compare: a comparison with the call on its right, written call-first (a table byte against a call)."""
from decomprepair import call_first_compare as c

SOURCE = '''u16 next(void);
extern u8 table[];
inline static unsigned short low(u16 v)
{
  return v & 0xFFFF;
}

void bump(s32 i)
{
  s32 k;
  k = i & 0xFFFF;
  if (((u8) (*((&table) + k))) < ((u32) low(next())))
  {
    *((&table) + k) = next();
  }
}
'''


def test_the_call_moves_to_the_left_and_the_operator_flips():
    (family, out), = c.variants(SOURCE, 'bump')
    assert family == 'call_first_compare'
    assert 'if (((u32) low(next())) > ((u8) (*((&table) + k))))' in out
    assert out.count('next()') == SOURCE.count('next()')


def test_a_side_effect_on_the_other_side_is_left_alone():
    source = SOURCE.replace('(*((&table) + k))', 'table[k++]')
    assert c.variants(source, 'bump') == []


def test_a_call_already_on_the_left_or_none_at_all_is_left_alone():
    flipped = SOURCE.replace('if (((u8) (*((&table) + k))) < ((u32) low(next())))', 'if (((u32) low(next())) > ((u8) (*((&table) + k))))')
    assert c.variants(flipped, 'bump') == []
    plain = SOURCE.replace('((u32) low(next()))', 'k')
    assert c.variants(plain, 'bump') == []


def test_a_logical_condition_is_left_alone():
    source = SOURCE.replace('if (((u8)', 'if (k && ((u8)')
    assert c.variants(source, 'bump') == []
