"""A 0/1 flag computed by tests, written as an inline predicate that returns.

Synthetic shape of a sound-sequence interpreter's slot check (KMC GCC 2.7.2); on the 1315-instruction interpreter the
predicate took 9595 -> 9000 (exact judge, decompdecomp's tests)."""
from decomprepair import flag_predicate_inline as m
from decomprepair import registry

SOURCE = '''typedef unsigned char u8;
typedef int s32;
extern u8 gTable[];
void set(s32);

void run(u8 *voice)
{
  s32 id;
  u8 channel;
  u8 a;
  u8 b;
  s32 owned;
  id = *((s32 *) (voice + 0x60));
  if (id != -1)
  {
    channel = voice[0x4A];
    owned = 0;
    if (channel != 0xFF)
    {
      a = id & 0xFF;
      b = gTable[a];
      owned = 0;
      if (a == b)
      {
        owned = 1;
      }
    }
  }
  else
  {
    owned = 0;
  }
  if (owned & 0xFF)
  {
    set(id);
  }
}
'''


def texts(source=SOURCE):
    found = m.variants(source, 'run')
    assert all(family == m.FAMILY for family, _ in found)
    return [text for _, text in found]


def test_the_flag_becomes_a_predicate():
    (text,) = texts()
    assert 'static inline s32 run_flag(s32 id, u8 * voice)' in text
    helper = text.split('static inline s32 run_flag')[1].split('void run(')[0]
    assert '  u8 channel;\n  u8 a;\n  u8 b;\n' in helper
    assert 'return 1;' in helper and helper.rstrip().endswith('return 0;\n}')
    assert 'owned' not in helper
    caller = text.split('void run(')[1]
    assert 'owned = run_flag(id, voice);\n  if (owned & 0xFF)' in caller
    assert 'u8 channel;' not in caller


def test_a_flag_set_to_one_before_more_work_is_left_alone():
    source = SOURCE.replace('        owned = 1;\n', '        owned = 1;\n        set(0);\n')
    assert texts(source) == []


def test_it_declares_itself():
    repair = next(r for r in registry.declared() if r.module == 'flag_predicate_inline')
    assert registry.problems(repair) == []
