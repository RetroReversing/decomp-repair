"""A switch arm's constant result written at its `break`, every arm at once.

Synthetic shape of a sound-sequence interpreter's handlers (KMC GCC 2.7.2); on the 1315-instruction interpreter the
two arms were 19185 -> 15930 together and worse alone (exact judge, decompdecomp's tests)."""
from decomprepair import arm_result_constant_sink as m
from decomprepair import registry

SOURCE = '''typedef int s32;
s32 check(void);
s32 lookup(s32);
void reset(s32, s32);

s32 run(s32 *voice, s32 op)
{
  s32 result;
  switch (op)
  {
    case 1:
      result = 0;
      if (voice[0] != 0xFF)
      {
        if (check() >= 3)
        {
          voice[1] = lookup(op);
        }
        else
        {
          goto other;
        }
      }
      break;
    case 2:
      result = 0;
      reset(voice[2], 1);
      break;
    case 3:
      result = 0;
      voice[3] = result;
      break;
    default:
      other:
      result = 0;
      break;
  }
  return result;
}
'''


def texts(source=SOURCE):
    found = m.variants(source, 'run')
    assert all(family == m.FAMILY for family, _ in found)
    return [text for _, text in found]


def test_every_arm_at_once_then_each_alone():
    together, first, second = texts()
    assert '''        }
      }
      result = 0;
      break;
    case 2:
      reset(voice[2], 1);
      result = 0;
      break;''' in together
    # an arm that reads the value keeps it where it is
    assert '''    case 3:
      result = 0;
      voice[3] = result;''' in together
    assert 'reset(voice[2], 1);\n      result = 0;' in second and 'case 1:\n      result = 0;' in second
    assert 'case 2:\n      result = 0;' in first


def test_a_goto_to_a_label_that_does_not_set_the_value_keeps_it():
    source = SOURCE.replace('      other:\n      result = 0;', '      other:\n      result = 2;')
    together = texts(source)[0]
    assert 'case 1:\n      result = 0;' in together and 'reset(voice[2], 1);\n      result = 0;' in together


def test_it_declares_itself():
    repair = next(r for r in registry.declared() if r.module == 'arm_result_constant_sink')
    assert registry.problems(repair) == []
