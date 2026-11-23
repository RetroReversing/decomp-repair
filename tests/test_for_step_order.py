"""The two steps of a `for` header swapped."""
from decomprepair import registry
from decomprepair.for_step_order import FAMILY, variants

SOURCE = """void walk(u8 *p, s32 n, s32 *out)
{
  s32 i;
  for (i = 0; i < n; i++, p += 3)
  {
    out[i] = p[0];
  }
}
"""


def test_the_steps_are_swapped():
    (family, child), = variants(SOURCE, 'walk')
    assert family == FAMILY
    assert 'for (i = 0; i < n; p += 3, i++)' in child and 'out[i] = p[0];' in child


def test_dependent_or_single_steps_are_declined():
    assert variants(SOURCE.replace('p += 3', 'p += i'), 'walk') == []
    assert variants(SOURCE.replace('i++, p += 3', 'i++'), 'walk') == []
    assert variants(SOURCE.replace('i++, p += 3', 'i++, i += 2'), 'walk') == []
    assert variants(SOURCE.replace('i++, p += 3', 'i++, step()'), 'walk') == []


def test_registry_declares_the_family():
    repair = registry.get('for_step_order')
    assert repair is not None and registry.problems(repair) == [] and FAMILY in repair.families
