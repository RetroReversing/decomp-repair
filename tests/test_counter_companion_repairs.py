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
    # a counter that doesn't start at 0 or isn't stepped by 1, or inits that aren't right before the loop
    assert c.variants(SOURCE.replace('j = 0;', 'j = 1;'), 'f') == []
    assert c.variants(SOURCE.replace('      j++;\n', '      j += 2;\n'), 'f') == []
    assert c.variants(SOURCE.replace('    do\n', '    h();\n    do\n'), 'f') == []
    # the steps must be the loop's last statements: a use after them would see the stepped value
    assert c.variants(SOURCE.replace('      f += 0xFF8;\n', '      f += 0xFF8;\n      h(f);\n'), 'f') == []
