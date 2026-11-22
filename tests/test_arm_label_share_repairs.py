from decomprepair.arm_label_share_repairs import FAMILY, variants

SOURCE = """void f(s32 n, s32 flip, u8 *rec)
{
  s32 x;
  if (n != 1)
  {
    x = 0x74;
    if (n == 2)
    {
      if (flip != 1)
      {
        rec[0x135] = 0;
      }
      else
      {
        goto L_a;
      }
    }
    else
    {
      goto L_b;
    }
  }
  else
  {
    L_a:
    x = 0x3A;

    L_b:
    rec[0x135] = 0;

  }
  use(x);
}
"""


def _shared(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_the_arm_that_repeats_the_labels_statement_jumps_to_the_label():
    found = _shared()
    assert len(found) == 1
    assert 'goto L_b;' in found[0].split('L_a:')[0].split('flip != 1')[1].split('else')[0]
    assert found[0].count('rec[0x135] = 0;') == 1


def test_an_arm_that_flows_elsewhere_or_a_label_that_returns_is_left_alone():
    elsewhere = SOURCE.replace('  use(x);', '  use(x);\n  use(x);').replace('    else\n    {\n      goto L_b;\n    }\n', '    else\n    {\n      goto L_b;\n    }\n    other();\n')
    assert not _shared(elsewhere)
    returning = SOURCE.replace('rec[0x135] = 0;\n\n  }', 'rec[0x135] = 0;\n    return;\n  }')
    assert not _shared(returning)  # the label's path returns, the arm's path goes on to use(x)
    looped = SOURCE.replace('if (n == 2)', 'while (n == 2)')
    assert not _shared(looped)


def test_asm_or_no_label_gives_nothing():
    assert not variants('void f(void) { g(); }\n', 'f')
    assert not variants(SOURCE.replace('x = 0x74;', 'asm("nop");'), 'f')
