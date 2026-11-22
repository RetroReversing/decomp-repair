from decomprepair.narrow_test_share_repairs import FAMILY, variants

SOURCE = """void f(s32 a, u8 flag)
{
  s32 x;
  s32 y;
  u16 z;
  x = 0x96;
  if (((s8) flag) == 0)
  {
    y = 1;
  }
  z = 0xA0;
  x = 0x24;
  if (((s8) flag) != 0)
  {
    x = 0x30;
  }
  use(x, y, z);
}
"""


def _shared(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_two_signed_narrow_reads_share_one_local():
    found = _shared()
    assert len(found) == 1
    text = found[0]
    assert text.count('(s8)') == 1
    assert '__repair_narrow_flag = (s8) flag;' in text
    assert text.index('__repair_narrow_flag = ') < text.index('if ((__repair_narrow_flag) == 0)')
    assert 'if ((__repair_narrow_flag) != 0)' in text
    assert text.index('s32 __repair_narrow_flag;') < text.index('x = 0x96;')
    assert text.index('s32 __repair_narrow_flag;') > text.index('u16 z;')


def test_a_write_a_label_or_a_closed_block_between_the_reads_blocks_it():
    assert not _shared(SOURCE.replace('z = 0xA0;', 'flag = 3;'))
    assert not _shared(SOURCE.replace('z = 0xA0;', 'again: z = 0xA0;'))
    nested = SOURCE.replace('if (((s8) flag) == 0)\n  {\n    y = 1;', 'if (a)\n  {\n    y = ((s8) flag) == 0;').replace('  }\n  z = 0xA0;', '  }\n  z = 0xA0;')
    assert not _shared(nested)


def test_different_variables_or_widths_do_not_pair_and_asm_is_skipped():
    assert not _shared(SOURCE.replace('(s8) flag) != 0', '(s16) flag) != 0'))
    assert not variants(SOURCE.replace('x = 0x96;', 'asm("nop");'), 'f')
    assert not variants('void f(void) { g(); }\n', 'f')
