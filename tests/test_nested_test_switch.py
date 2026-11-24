"""Two nested tests of one value written as the two-case `switch` they came from.

Synthetic shape of a sound-sequence interpreter's handler (KMC GCC 2.7.2); on the 1315-instruction interpreter the
`switch` took 11300 -> 10360 (exact judge, decompdecomp's tests)."""
from decomprepair import nested_test_switch as m
from decomprepair import registry

SOURCE = '''typedef unsigned char u8;
typedef int s32;
extern u8 gMode;
void update(s32 *);
void clear(s32);

s32 run(s32 *voice)
{
  s32 result;
  if (gMode != 0)
  {
    result = 0;
    if (gMode != 1)
    {
    }
    else
    {
      update(voice);
      voice[9] |= 0x1800;
    }
  }
  else
  {
    voice[9] &= ~0x800;
    clear(voice[1]);
    result = 2;
  }
  return result;
}
'''


def texts(source=SOURCE):
    found = m.variants(source, 'run')
    assert all(family == m.FAMILY for family, _ in found)
    return [text for _, text in found]


def test_the_tests_become_a_switch_with_the_shared_statements_on_their_paths():
    (text,) = texts()
    assert '''  switch (gMode)
  {
    case 0:
      voice[9] &= ~0x800;
      clear(voice[1]);
      result = 2;
      break;

    case 1:
      result = 0;
      update(voice);
      voice[9] |= 0x1800;
      break;

    default:
      result = 0;
      break;
  }
  return result;''' in text


def test_an_inner_test_written_with_equals():
    source = SOURCE.replace('''    if (gMode != 1)
    {
    }
    else
    {''', '''    if (gMode == 1)
    {''')
    (text,) = texts(source)
    assert 'case 1:\n      result = 0;\n      update(voice);' in text


def test_a_break_of_the_enclosing_loop_is_left_alone():
    source = SOURCE.replace('      update(voice);\n', '      update(voice);\n      break;\n')
    assert texts(source) == []


def test_it_declares_itself():
    repair = next(r for r in registry.declared() if r.module == 'nested_test_switch')
    assert registry.problems(repair) == []
