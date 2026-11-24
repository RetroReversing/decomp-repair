"""An arm that falls through into its own `default:` instead of m2c's label in its `else`.

Synthetic shape of a sound-sequence interpreter (KMC GCC 2.7.2); on the 1315-instruction interpreter the fall-through
took 13735 -> 11545 (exact judge, decompdecomp's tests)."""
from decomprepair import default_label_fallthrough as m
from decomprepair import registry

SOURCE = '''typedef int s32;
s32 lookup(s32);

s32 run(s32 *voice, s32 op)
{
  s32 result;
  s32 entry;
  switch (op)
  {
    case 2:
      if (voice[1] >= 3)
      {
        entry = lookup(op);
        result = 0;
        if (entry != 0)
        {
          voice[0] = entry;
        }
      }
      else
      {
        default:
        block_205:
        result = 0;
      }
      break;

    case 3:
      if (voice[2] != 0)
      {
        result = 1;
        break;
      }
      goto block_205;
  }
  return result;
}
'''


def texts(source=SOURCE):
    found = m.variants(source, 'run')
    assert all(family == m.FAMILY for family, _ in found)
    return [text for _, text in found]


def test_the_arm_falls_through_into_default():
    (text,) = texts()
    assert 'else' not in text.split('case 3')[0]
    assert '''          voice[0] = entry;
        }
      }
      default:
        block_205:
        result = 0;
        break;''' in text
    assert 'goto block_205;' in text


def test_a_then_block_that_does_not_set_the_value_last_is_left_alone():
    source = SOURCE.replace('        result = 0;\n        if (entry != 0)', '        result = 0;\n        result = entry;\n        if (entry != 0)')
    assert texts(source) == []
    assert texts(SOURCE.replace('        result = 0;\n        if (entry', '        result = 2;\n        if (entry')) == []


def test_it_declares_itself():
    repair = next(r for r in registry.declared() if r.module == 'default_label_fallthrough')
    assert registry.problems(repair) == []
