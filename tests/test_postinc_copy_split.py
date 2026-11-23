"""`x = v++;` written through a second local: the copy and the increment, then the assignment.

Synthetic shape of one loop of a mixing function (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`). The exact-judge
replay is in decompdecomp's tests (it needs the compiler): three such loops together 1680 -> 1110, 1150 -> 220 from the
state the other steps leave."""
from decomprepair import postinc_copy_split as m
from decomprepair import registry

SOURCE = '''typedef unsigned int u32;
extern u32 g_cursor;
extern int g_limit;
void walk(int *table, int count)
{
  u32 cursor;
  cursor = g_cursor;
  do
  {
    u32 index;
    index = cursor++;
    call(table[index & 0xFFFF]);
  }
  while (count-- > 0);
  {
    u32 other;
    other = cursor++;
    call(table[other]);
  }
}
'''


def texts(source=SOURCE):
    found = m.variants(source, 'walk')
    assert all(family == m.FAMILY for family, _ in found)
    return [text for _, text in found]


def test_each_statement_gets_a_temporary_declared_beside_its_destination():
    found = texts()
    one = next(t for t in found if t.count('__repair_postinc_0 = cursor++;') == 1 and '__repair_postinc_1' not in t
               and 'index = __repair_postinc_0;' in t)
    assert 'u32 index; u32 __repair_postinc_0;' in one
    assert 'other = cursor++;' in one  # the other loop is left alone in the single-site child


def test_one_child_changes_every_site_together():
    both = next(t for t in texts() if '__repair_postinc_1' in t)
    assert 'other = __repair_postinc_1;' in both
    assert 'index = __repair_postinc_0;' in both
    assert 'u32 other; u32 __repair_postinc_1;' in both


def test_a_destination_without_a_declaration_is_left_alone():
    assert texts(SOURCE.replace('    u32 index;\n', '')) != [] and all('index = __repair' not in t for t in texts(SOURCE.replace('    u32 index;\n', '')))


def test_a_second_run_does_nothing():
    assert m.variants(texts()[0], 'walk') == []


def test_it_declares_itself_to_the_registry():
    assert any(r.module == 'postinc_copy_split' for r in registry.declared())
