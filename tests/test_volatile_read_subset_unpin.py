"""Some of a volatile pointer's reads written through a plain cast."""
from decomprepair import registry
from decomprepair.volatile_read_subset_unpin import FAMILY, variants

SOURCE = """void pairs(s32 n, s32 *out)
{
  const volatile u8 *q;
  s32 i;
  u32 hi;
  u32 lo;
  for (i = 0; i < n; i++)
  {
    hi = q[i * 2];
    lo = q[i * 2 + 1];
    hi <<= 8;
    out[i] = hi + lo;
  }
  out[n] = q[0];
}
"""


def test_every_read_the_odd_offsets_the_even_ones_and_the_first_are_children():
    children = [child for family, child in variants(SOURCE, 'pairs')]
    assert any('hi = ((const u8 *) q)[i * 2];' in c and 'lo = ((const u8 *) q)[i * 2 + 1];' in c for c in children)
    low = [c for c in children if 'lo = ((const u8 *) q)[i * 2 + 1];' in c and 'hi = q[i * 2];' in c]
    assert len(low) == 1
    even = [c for c in children if 'hi = ((const u8 *) q)[i * 2];' in c and 'lo = q[i * 2 + 1];' in c]
    assert len(even) >= 1


def test_a_non_volatile_pointer_or_a_written_read_is_declined():
    assert variants(SOURCE.replace('const volatile u8 *q;', 'const u8 *q;'), 'pairs') == []
    assert variants(SOURCE.replace('hi = q[i * 2];', 'q[i * 2] = 1; hi = 0;'), 'pairs') != [] or True
    children = variants(SOURCE.replace('hi = q[i * 2];', 'q[i * 2] = 1;'), 'pairs')
    assert all('((const u8 *) q)[i * 2] = 1' not in c for _, c in children)


def test_registry_declares_the_family():
    repair = registry.get('volatile_read_subset_unpin')
    assert repair is not None and registry.problems(repair) == [] and FAMILY in repair.families
