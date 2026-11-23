"""A scratch local shared by the arms of a switch, given a block of its own in every arm that sets it first."""
from decomprepair import registry
from decomprepair.arm_scratch_block_locals import FAMILY, variants

SOURCE = """void walk(u8 *p, s32 *out, s32 n)
{
  u8 x;
  u8 y;
  s32 i;
  switch (p[0])
  {
    case 0:
      for (i = 0; i < n; i++)
      {
        x = p[i];
        y = p[i + 1];
        out[0] += x + y;
      }
      goto done;

    case 1:
      for (i = 0; i < n; i++)
      {
        x = p[i + 2];
        y = p[i + 3];
        out[1] += x * y;
      }
      goto done;

    case 2:
      x = p[1];
      y = x;
      out[2] = y;
      break;
  }
  done:
  out[3] = 0;
}
"""


def test_the_arms_that_set_the_names_first_get_blocks_and_each_arm_alone_is_a_child():
    children = [child for family, child in variants(SOURCE, 'walk')]
    assert len(children) >= 3
    everything = children[0]
    assert 'case 0: {' in everything and 'case 1: {' in everything and 'case 2: {' in everything
    assert everything.count('u8 x;') == 3 and everything.index('u8 x;') > everything.index('switch')
    assert 'goto done;' in everything and everything.index('}', everything.index('case 0:')) < everything.index('goto done;')
    assert any('case 0: {' in c and 'case 1: {' not in c for c in children)


def test_a_name_read_outside_the_arms_or_before_it_is_set_is_not_split():
    outside = variants(SOURCE.replace('out[3] = 0;', 'out[3] = x;'), 'walk')
    assert outside
    for _, child in outside:
        arms = child[child.index('switch'):]
        assert 'u8 x;' not in arms and 'u8 y;' in arms
    for edited in (SOURCE.replace('x = p[i];\n        y = p[i + 1];', 'y = x;\n        x = p[i];'),
                   SOURCE.replace('x = p[i];', 'if (n) x = p[i];')):
        for _, child in variants(edited, 'walk'):
            first_arm = child[child.index('case 0:'):child.index('case 1:')]
            assert 'u8 x;' not in first_arm


def test_registry_declares_the_family():
    repair = registry.get('arm_scratch_block_locals')
    assert repair is not None and registry.problems(repair) == [] and FAMILY in repair.families
