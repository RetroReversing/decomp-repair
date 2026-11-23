"""A packed word's constant written first in its `|` chain."""
from decomprepair import registry
from decomprepair.or_constant_lead import FAMILY, variants

SOURCE = """void pack(GfxPair *gfx, u32 n, u32 m)
{
  gfx->w0 = (n << 12) | (((n & 127) << 1) | 0x01000000);
  gfx->w1 = (m << 12) | (((m & 127) << 1) | 0x01000000);
  gfx->w2 = (m << 4) | 0x06000000;
}
"""


def test_the_constant_leads_and_identical_chains_are_one_child():
    children = [child for family, child in variants(SOURCE, 'pack')]
    first = children[0]
    assert 'gfx->w0 = 0x01000000 | (n << 12) | ((n & 127) << 1);' in first
    assert 'gfx->w2 = (m << 4) | 0x06000000;' in first
    assert 'gfx->w2 = 0x06000000 | (m << 4);' in children[-1] and 'gfx->w1 = 0x01000000 | (m << 12) | ((m & 127) << 1);' in children[-1]


def test_a_chain_that_already_leads_or_has_two_constants_is_declined():
    assert variants('void f(u32 *o, u32 a)\n{\n  *o = 4 | a;\n}\n', 'f') == []
    assert variants('void f(u32 *o, u32 a)\n{\n  *o = a | 4 | 8;\n}\n', 'f') == []
    assert variants('void f(u32 *o, u32 a, u32 b)\n{\n  *o = a || b | 8;\n}\n', 'f') == []


def test_registry_declares_the_family():
    repair = registry.get('or_constant_lead')
    assert repair is not None and registry.problems(repair) == [] and FAMILY in repair.families
