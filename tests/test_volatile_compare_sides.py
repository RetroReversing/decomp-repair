from decomprepair.volatile_compare_sides import FAMILY, variants

SOURCE = """extern s32 gBound;
inline static volatile s32 rd(volatile s32 *arg0)
{
  return *arg0;
}

void f(void)
{
  s16 i = 0;
  do
  {
    i++;
  }
  while (((s16) i) < rd((volatile s32 *) (&gBound)));
}
"""


def test_a_helper_read_of_a_volatile_goes_first_and_the_operator_mirrors():
    [(family, text)] = variants(SOURCE, 'f')
    assert family == FAMILY
    assert 'while (rd((volatile s32 *) (&gBound)) > ((s16) i));' in text


def test_a_cast_read_is_a_volatile_read_too():
    text = SOURCE.replace('rd((volatile s32 *) (&gBound))', '*(volatile s32 *) &gBound')
    [(_, out)] = variants(text, 'f')
    assert 'while (*(volatile s32 *) &gBound > ((s16) i));' in out


def test_an_operand_with_a_call_or_no_volatile_is_left_alone():
    assert variants(SOURCE.replace('((s16) i) <', 'g(i) <'), 'f') == []
    assert variants(SOURCE.replace('volatile', ''), 'f') == []


def test_the_volatile_side_already_first_is_not_swapped_back():
    assert variants(SOURCE.replace('((s16) i) < rd((volatile s32 *) (&gBound))', 'rd((volatile s32 *) (&gBound)) > ((s16) i)'), 'f') == []
