"""A global an arm stores to after a call, written through a pointer taken at the arm's start.

Synthetic shape of a sound-sequence interpreter (KMC GCC 2.7.2); on the 1315-instruction interpreter two arms took
14360 -> 13735 (exact judge, decompdecomp's tests)."""
from decomprepair import arm_global_store_pointer as m
from decomprepair import registry

SOURCE = '''typedef unsigned int u32;
typedef int s32;
extern u32 gCmd;
extern s32 gOther;
void slot(s32);
s32 apply(s32 *, u32 *);

s32 run(s32 *voice, s32 op)
{
  s32 result;
  switch (op)
  {
    case 1:
      voice[1] = gCmd;
      slot(voice[2]);
      gCmd = 4;
      result = apply(voice, &gCmd);
      break;

    case 2:
      gCmd = 5;
      result = apply(voice, &gCmd);
      break;

    case 3:
      slot(1);
      gOther = 2;
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


def test_each_arm_storing_after_a_call_gets_its_pointer():
    together, first, second = texts()
    assert '''    case 1:
      {
        u32 *ptr = &gCmd;
      voice[1] = gCmd;
      slot(voice[2]);
      *ptr = 4;''' in together
    assert 's32 *ptr = &gOther;' in together and '*ptr = 2;' in together
    # no call before the store: left alone
    assert 'case 2:\n      gCmd = 5;' in together
    assert '*ptr = 4;' in first and 'gOther = 2;' in first
    assert 'gCmd = 4;' in second and '*ptr = 2;' in second


def test_it_declares_itself():
    repair = next(r for r in registry.declared() if r.module == 'arm_global_store_pointer')
    assert registry.problems(repair) == []
