"""Companions of a loop counter, written off the counter."""
from decomprepair import counter_companion_repairs as c

SOURCE = '''void f(void)
{
  s32 f;
  u32 j;
  char *k;
  s32 a;
  if (D_801002D8 != 0)
  {
    j = 0; k = &D_800E6A84; f = 0;
    do
    {
      if ((*((u8 *) k)) != 0)
      {
        D_800EDA8C = f + D_800E5AC4;
        a = *(D_800E6A88 + f);
        g(a);
        *((u8 *) k) = 0;
        *(D_800E6A85 + f) = 1;
      }
      k += 0xFF8;
      j++;
      f += 0xFF8;
    }
    while (8U > j);
  }
}
'''


def test_both_companions_off_the_counter():
    # A MIPS function with this loop: 535; written off the counter its preheader had the target's order.
    (family, both), (_, only_k), (_, only_f) = c.variants(SOURCE, 'f')
    assert family == 'counter_companion'
    assert '    j = 0;\n    do\n' in both and 'k = &D_800E6A84' not in both and 'f = 0' not in both
    assert 'if ((*((u8 *) ((char *) (&D_800E6A84) + j * 0xFF8))) != 0)' in both
    assert 'D_800EDA8C = (j * 0xFF8) + D_800E5AC4;' in both
    assert 'a = *(D_800E6A88 + (j * 0xFF8));' in both
    assert '*(D_800E6A85 + (j * 0xFF8)) = 1;\n      }\n      j++;\n    }\n    while (8U > j);' in both
    assert 'f += 0xFF8;' in only_k and 'k += 0xFF8' not in only_k and 'f = 0' in only_k
    assert 'k += 0xFF8;' in only_f and 'f += 0xFF8' not in only_f and 'k = &D_800E6A84' in only_f


def test_left_alone_otherwise():
    # a companion read after the loop, or whose address is taken, stays as it is
    after = SOURCE.replace('    while (8U > j);\n  }', '    while (8U > j);\n    h(f);\n  }')
    (_, only_k), = c.variants(after, 'f')
    assert 'f += 0xFF8;' in only_k and 'f = 0' in only_k and 'k += 0xFF8' not in only_k
    (_, only_f), = c.variants(SOURCE.replace('g(a);', 'g(&k);'), 'f')
    assert 'k += 0xFF8;' in only_f and 'f += 0xFF8' not in only_f
    # a counter that doesn't start at a constant or isn't stepped by 1
    assert c.variants(SOURCE.replace('j = 0;', 'j = n;'), 'f') == []
    assert c.variants(SOURCE.replace('      j++;\n', '      j += 2;\n'), 'f') == []
    # an init earlier than the statements right before the loop only when it is a constant or a symbol's address,
    # and nothing between names the variable
    assert c.variants(SOURCE.replace('k = &D_800E6A84;', 'k = p;').replace('    do\n', '    h();\n    do\n'),
                      'f')[0][1].count('k += 0xFF8;') == 1
    assert c.variants(SOURCE.replace('    do\n', '    h(f);\n    do\n'), 'f')[0][1].count('f += 0xFF8;') == 1
    # the steps must be the loop's last statements: a use after them would see the stepped value
    assert c.variants(SOURCE.replace('      f += 0xFF8;\n', '      f += 0xFF8;\n      h(f);\n'), 'f') == []


def test_counter_from_a_constant():
    # j from 1: the companion is its init plus (j - 1) strides
    (_, both), _, _ = c.variants(SOURCE.replace('j = 0;', 'j = 1;'), 'f')
    assert 'D_800EDA8C = ((j - 1) * 0xFF8) + D_800E5AC4;' in both
    assert '((char *) (&D_800E6A84) + (j - 1) * 0xFF8)' in both


VOICES = '''s32 f(void)
{
  char *p;
  s32 i;
  s32 off;
  {
    i = -4;
  }
  g();
  p = D_8017B20C;
  off = -0x70;
  if (i < (D_8017B204 - 4))
  {
    do
    {
      if (*((s32 *) p) != 0)
      {
        alSynStopVoice(D_8017B4A0, D_8017B208 + off);
      }
      {
        off += 0x1C;
      }
      {
        {
          i += 1;
        }
      }
      {
      }
      {
        p += 0x13C;
      }
    }
    while (i < (D_8017B204 - 4));
  }
  return 0;
}
'''


def test_counter_from_minus_four_with_braced_steps():
    # An SN GCC 2.7.2 audio voice loop counted from -4 beside a byte offset from -0x70 (= -4 * 0x1C), in the plain form
    # of a saved best (fences opened to bare blocks): 170 -> 0 written as `D_8017B208 + i * 0x1C`.
    (family, text), = c.variants(VOICES, 'f')
    assert family == 'counter_companion'
    assert 'alSynStopVoice(D_8017B4A0, D_8017B208 + (i * 0x1C));' in text
    assert 'off = -0x70' not in text and 'off += 0x1C' not in text
    assert 'i += 1;' in text and 'p += 0x13C;' in text and 'p = D_8017B20C;' in text
    # an offset that doesn't start at a multiple of the counter's start keeps its base
    (_, other), = c.variants(VOICES.replace('off = -0x70;', 'off = 8;'), 'f')
    assert 'D_8017B208 + (8 + (i + 4) * 0x1C)' in other
    # a step followed by a statement that isn't one ends the run
    assert c.variants(VOICES.replace('      {\n      }\n', '      {\n        h();\n      }\n'), 'f') == []
