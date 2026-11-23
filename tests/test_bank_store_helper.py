"""A banked-or-default byte store written once as an inline helper.

Synthetic shape of a controller-word handler (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`): a coarse and a fine half
of a 14-bit value stored in each arm of an `if` chain, each store choosing the banked table or the default one. The
exact-judge replay is in decompdecomp's tests (it needs the compiler): the `shifted` child took the 239-instruction
handler 3530 -> 0, the other two children 6995 and 9025."""
from decomprepair import bank_store_helper as m
from decomprepair import registry

SOURCE = '''typedef unsigned char u8;
typedef unsigned short u16;
extern u8 banks[][16][0x86];
extern u8 fallback[][0x86];

void put(u8 cc, u8 row, u8 bank, u16 value)
{
  if (cc < 0x40)
  {
    if (bank != 0xFF) { banks[bank][row][cc & 0x1F] = (value >> 7) & 0x7F; } else { fallback[row][cc & 0x1F] = (value >> 7) & 0x7F; }
    if (bank != 0xFF) { banks[bank][row][(cc & 0x1F) | 0x20] = value & 0x7F; } else { fallback[row][(cc & 0x1F) | 0x20] = value & 0x7F; }
  }
  else
  {
    if (bank != 0xFF) { banks[bank][row][cc] = (value >> 7) & 0x7F; } else { fallback[row][cc] = (value >> 7) & 0x7F; }
  }
}
'''


def texts(source=SOURCE):
    found = m.variants(source, 'put')
    assert all(family == m.FAMILY for family, _ in found)
    return [text for _, text in found]


def test_three_children_by_what_happens_to_the_mask():
    plain, masked, shifted = texts()
    assert 'inline static void store_by_bank(u8 r, u8 i, u8 b, u8 v)' in plain
    assert 'D_' not in plain and 'banks[b][i][r] = v;' in plain
    assert 'store_by_bank(cc & 0x1F, row, bank, (value >> 7) & 0x7F);' in plain
    assert 'banks[b][i][r] = v & 0x7F;' in masked
    assert 'store_by_bank(cc & 0x1F, row, bank, value >> 7);' in masked
    assert 'store_by_bank((cc & 0x1F) | 0x20, row, bank, value);' in masked
    # the combination: the helper masks, the shifted half drops its mask, the low half keeps it
    assert 'banks[b][i][r] = v & 0x7F;' in shifted
    assert 'store_by_bank(cc & 0x1F, row, bank, value >> 7);' in shifted
    assert 'store_by_bank((cc & 0x1F) | 0x20, row, bank, value & 0x7F);' in shifted
    assert 'store_by_bank(cc, row, bank, value >> 7);' in shifted
    assert 'if (bank' not in shifted.split('void put')[1]


def test_the_arm_order_and_test_are_kept():
    source = '''typedef unsigned char u8;
extern u8 banks[][16][0x86];
extern u8 fallback[][0x86];

void put(u8 cc, u8 row, u8 bank, u8 value)
{
  if (bank == 0xFF) fallback[row][cc] = value;
  else banks[bank][row][cc] = value;
  if (bank == 0xFF) fallback[row][cc + 1] = value;
  else banks[bank][row][cc + 1] = value;
}
'''
    (only,) = texts(source)
    helper = only.split('void put')[0]
    assert helper.index('if (b == 0xFF)') < helper.index('fallback[i][r] = v;') < helper.index('banks[b][i][r] = v;')
    assert 'store_by_bank(cc + 1, row, bank, value);' in only
    # a site with the other arm first is another helper's: one site left is not enough
    mixed = source.replace('if (bank == 0xFF) fallback[row][cc + 1] = value;\n  else banks[bank][row][cc + 1] = value;',
                           'if (bank != 0xFF) banks[bank][row][cc + 1] = value;\n  else fallback[row][cc + 1] = value;')
    assert m.variants(mixed, 'put') == []


def test_sites_of_another_table_or_test_are_left_alone():
    assert m.variants(SOURCE.replace('fallback[row][cc & 0x1F]', 'other[row][cc & 0x1F]'), 'put') == []
    assert m.variants(SOURCE.replace('bank != 0xFF', 'bank > 0xFF'), 'put') == []
    assert m.variants(SOURCE.replace('banks[bank][row]', 'banks[bank][other]'), 'put') == []


def test_the_value_is_not_masked_alike_only_the_plain_child_is_offered():
    source = SOURCE.replace('value & 0x7F; } else { fallback[row][(cc & 0x1F) | 0x20] = value & 0x7F;',
                            'value & 0x3F; } else { fallback[row][(cc & 0x1F) | 0x20] = value & 0x3F;')
    assert len(texts(source)) == 1


def test_it_declares_itself():
    assert 'bank_store_helper' in {r.module for r in registry.declared()}
    repair = next(r for r in registry.declared() if r.module == 'bank_store_helper')
    assert registry.problems(repair) == []
