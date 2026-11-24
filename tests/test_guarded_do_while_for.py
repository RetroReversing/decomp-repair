"""m2c's guarded do/while with the tail copied into the else, written as the `for` it was.

Synthetic shape of a sound-sequence interpreter's voice scan (KMC GCC 2.7.2); on the 1315-instruction interpreter the
`for` took 8280 -> 6141 (exact judge, decompdecomp's tests)."""
from decomprepair import guarded_do_while_for as m
from decomprepair import registry

SOURCE = '''typedef unsigned int u32;
typedef int s32;
extern u32 gCount;
extern s32 gHandles[];
extern s32 gFlags[];

s32 scan(s32 op, u32 key)
{
  s32 result;
  u32 i;
  s32 offset;
  switch (op)
  {
    case 9:
      i = 0;
      {
        u32 count = gCount;
        if (count != 0)
        {
          offset = 0;
          do
          {
            if (*((s32 *) (((char *) gHandles) + offset)) == (key | i))
            {
              *((s32 *) (((char *) gFlags) + offset)) |= 8;
            }
            i += 1;
            offset += 0x1A0;
          }
          while (i < count);
          result = 0;
        }
        else
        {
          result = 0;
          break;
        }
      }
      break;
  }
  return result;
}
'''


def texts(source=SOURCE):
    found = m.variants(source, 'scan')
    assert all(family == m.FAMILY for family, _ in found)
    return [text for _, text in found]


def test_the_guarded_loop_becomes_a_for():
    (text,) = texts()
    assert '''        offset = 0;
        for (i = 0; i < count; i++, offset += 0x1A0)
        {
          if (*((s32 *) (((char *) gHandles) + offset)) == (key | i))
          {
            *((s32 *) (((char *) gFlags) + offset)) |= 8;
          }
        }
        result = 0;
      }
      break;''' in text
    assert 'i = 0;\n      {' not in text and 'do' not in text.split('case 9')[1]


def test_an_else_that_does_something_else_is_left_alone():
    assert texts(SOURCE.replace('          result = 0;\n          break;', '          result = 1;\n          break;')) == []


def test_it_declares_itself():
    repair = next(r for r in registry.declared() if r.module == 'guarded_do_while_for')
    assert registry.problems(repair) == []
