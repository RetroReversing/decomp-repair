"""Locals holding one narrow load at either width, and a search's symbol base written out."""
from decomprepair.local_load_widths import FAMILY_BASE, FAMILY_WIDTH, REPAIR, variants

SOURCE = """void step(void *p, s32 n)
{
  char *__base_sTable;
  s8 idx;
  s32 delta;
  s32 sum;
  idx = *((s8 *) (((char *) p) + 0xE));
  delta = *((s8 *) (D_800C46A0 + (idx * 0xE8)));
  sum = idx + n;
  __base_sTable = sTable;
  use(*((u16 *) (__base_sTable + (delta * 0xE8))), sum);
}
"""


def test_the_base_first_then_all_narrow_all_wide_then_each():
    found = variants(SOURCE, 'step')
    assert [family for family, _ in found][:3] == [FAMILY_BASE, FAMILY_WIDTH, FAMILY_WIDTH]
    base = found[0][1]
    assert '__base_' not in base and 'use(*((u16 *) (sTable + (delta * 0xE8))), sum);' in base
    assert '  s8 idx;\n  s8 delta;' in found[1][1]
    assert '  s32 idx;\n  s32 delta;' in found[2][1]
    # with two locals each one alone at its other width is one of the two group children: offered once
    assert len(found) == 3


def test_a_local_with_another_kind_of_set_keeps_its_width():
    found = variants(SOURCE.replace('  sum = idx + n;\n', '  sum = idx + n;\n  delta = n;\n'), 'step')
    assert all('s8 delta;' not in text for _, text in found)


def test_it_declares_itself():
    assert REPAIR['variants'] is variants and set(REPAIR['families']) == {FAMILY_BASE, FAMILY_WIDTH}
