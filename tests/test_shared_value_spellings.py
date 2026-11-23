"""Products and a field update m2c spelled through locals, written back for cse (a 1300-instruction routine)."""
from decomprepair.shared_value_spellings import FAMILY_FIELD, FAMILY_PRODUCT, REPAIR, variants

SOURCE = """void step(void *arg0, char *base)
{
  s32 temp_a1_2;
  s32 temp_a3;
  s32 idx;
  s8 delta;
  void *p;
  p = *((void **) (((char *) arg0) + 0x68));
  idx = *((s8 *) (((char *) p) + 0xE));
  temp_a3 = idx * 8;
  temp_a1_2 = idx * 0xE8;
  delta = *((s8 *) (D_800C46A0 + temp_a1_2));
  if (delta)
  {
    *((s8 *) (((char *) p) + 0xE)) = (s8) (idx + delta);
  }
  else
  {
    use(temp_a1_2 + base, base + temp_a3);
  }
}
"""


def children(source, family):
    return [text for fam, text in variants(source, 'step') if fam == family]


def test_every_product_is_inlined_together_first_then_alone():
    found = children(SOURCE, FAMILY_PRODUCT)
    assert len(found) == 3
    both = found[0]
    assert 'temp_a3' not in both and 'temp_a1_2' not in both
    assert 'D_800C46A0 + (idx * 0xE8)' in both and 'use((idx * 0xE8) + base, base + (idx * 8));' in both
    assert sum('temp_a3' in text for text in found[1:]) == 1


def test_a_product_whose_operand_changes_first_stays():
    source = SOURCE.replace('  if (delta)\n', '  idx = 3;\n  if (delta)\n')
    assert children(source, FAMILY_PRODUCT) == []


def test_the_field_add_becomes_a_compound_update():
    [child] = children(SOURCE, FAMILY_FIELD)
    assert '*((s8 *) (((char *) p) + 0xE)) += delta;' in child
    assert 'idx = *((s8 *) (((char *) p) + 0xE));' in child


def test_a_field_written_between_keeps_the_store():
    source = SOURCE.replace('  if (delta)\n', '  *((s8 *) (((char *) p) + 0xE)) = 0;\n  if (delta)\n')
    assert children(source, FAMILY_FIELD) == []
    source = SOURCE.replace('  if (delta)\n', '  p = arg0;\n  if (delta)\n')
    assert children(source, FAMILY_FIELD) == []


def test_it_declares_itself():
    assert REPAIR['variants'] is variants and set(REPAIR['families']) == {FAMILY_FIELD, FAMILY_PRODUCT}
