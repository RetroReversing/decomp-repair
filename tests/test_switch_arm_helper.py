"""Switch arms that differ only in their constants, written once as an inline helper.

Synthetic shape of a sound-sequence interpreter's marker opcodes (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`):
the exact-judge replay is in decompdecomp's tests; on the 1315-instruction interpreter's m2c draft the helper took
69922 -> 63857, and 29955 -> 22323 on a searched best whose arms were written the same way."""
from decomprepair import registry
from decomprepair import switch_arm_helper as m

SOURCE = '''typedef unsigned char u8;
typedef int s32;
extern u8 gArg;
s32 mark(s32);

void tick(char *voice, s32 op)
{
  s32 flags_a;
  u8 n_a;
  s32 flags_b;
  u8 n_b;
  s32 flags_c;
  u8 n_c;
  s32 result;
  switch (op)
  {
    case 1:
      flags_a = *((s32 *) (voice + 0x24));
      n_a = voice[0xD4];
      if ((!(flags_a & 0x200000) | (gArg == 0)) != 0)
      {
        *((s32 *) (voice + 0x24)) = flags_a | 0x200000;
        voice[0xD4] = 0;
      }
      voice[0xC4 + n_a] = mark(0x200000);
      goto done;
    case 2:
      flags_b = *((s32 *) (voice + 0x24));
      n_b = voice[0xE6];
      if ((!(flags_b & 0x400000) | (gArg == 0)) != 0)
      {
        *((s32 *) (voice + 0x24)) = flags_b | 0x400000;
        voice[0xE6] = 0;
      }
      voice[0xD6 + n_b] = mark(0x400000);
      goto done;
    case 3:
      flags_c = *((s32 *) (voice + 0x24));
      n_c = voice[0x10A];
      if ((!(flags_c & 0x800000) | (gArg == 0)) != 0)
      {
        *((s32 *) (voice + 0x24)) = flags_c | 0x800000;
        voice[0x10A] = 0;
      }
      voice[0xFA + n_c] = mark(0x800000);
      goto done;
    case 4:
      result = 1;
      break;
  }
  done:
  return;
}
'''


def texts(source=SOURCE):
    found = m.variants(source, 'tick')
    assert all(family == m.FAMILY for family, _ in found)
    return [text for _, text in found]


def test_one_helper_with_the_varying_constants_as_parameters():
    first, reverse = texts()
    assert 'static inline void tick_arm_1(char * voice, int k0, int k1, int k2)' in first
    assert '  s32 flags_a;\n  u8 n_a;\n' in first
    # the constants in the order they first appear; the bit is one parameter wherever it is written
    assert 'n_a = voice[k0];' in first and 'flags_a & k1' in first and 'voice[k2 + n_a] = mark(k1);' in first
    assert 'tick_arm_1(voice, 0xD4, 0x200000, 0xC4);\n        goto done;' in first
    assert 'tick_arm_1(voice, 0x10A, 0x800000, 0xFA);' in first
    # the arm-private locals now live in the helper only
    assert 's32 flags_b;' not in first and 'u8 n_c;' not in first
    assert 'result = 1;' in first
    assert 'tick_arm_1(char * voice, int k0, int k1, int k2)' in reverse
    assert 'tick_arm_1(voice, 0xC4, 0x200000, 0xD4);' in reverse


def test_arms_that_write_a_shared_variable_are_left_alone():
    source = SOURCE.replace('voice[0xC4 + n_a] = mark(0x200000);', 'voice[0xC4 + n_a] = mark(0x200000); result = 2;')
    source = source.replace('voice[0xD6 + n_b] = mark(0x400000);', 'voice[0xD6 + n_b] = mark(0x400000); result = 3;')
    source = source.replace('voice[0xFA + n_c] = mark(0x800000);', 'voice[0xFA + n_c] = mark(0x800000); result = 4;')
    assert texts(source) == []


def test_fewer_than_three_alike_arms_are_left_alone():
    source = SOURCE.replace('n_c = voice[0x10A];', 'n_c = voice[0x10A] + 1;')
    assert texts(source) == []


def test_it_declares_itself():
    repair = next(r for r in registry.declared() if r.module == 'switch_arm_helper')
    assert registry.problems(repair) == []
