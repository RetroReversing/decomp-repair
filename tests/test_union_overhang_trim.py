"""A frame union's overhanging view trimmed, and spilled spXX locals declared in slot order."""
import re

from decomprepair import registry
from decomprepair.union_overhang_trim import FAMILIES, spill_order, trims, variants

CODE = '''typedef float f32;
typedef short s16;
void use(f32 *, f32 *);

void sweep(void *arg0, f32 r)
{
  union
  {
    s16 angles[3];
    f32 data[6];
    struct
    {
      f32 pad[4];
      f32 lower[3];
    } bounds;
  } workspace;
  f32 upper[3];
  void *spEC;
  char sp147;
  void *spE4;
  spE4 = arg0;
  spEC = arg0;
  sp147 = 1;
  workspace.bounds.lower[0] = r;
  workspace.bounds.lower[2] -= r;
  {
    f32 *lower = workspace.bounds.lower;
    use(lower, upper);
  }
  use(workspace.data, (f32 *) spE4);
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_the_view_is_written_into_the_plain_array_and_dropped():
    (child,) = trims(CODE, 'sweep')
    text = squash(child)
    assert 'bounds' not in text and 'pad[4]' not in text
    assert 'workspace.data[4] = r;' in text and 'workspace.data[6] -= r;' in text
    assert 'f32 *lower = (&workspace.data[4]);' in text


def test_spilled_slot_names_are_declared_in_slot_order():
    text = squash(spill_order(CODE, 'sweep'))
    assert text.index('void *spE4;') < text.index('void *spEC;') < text.index('char sp147;')
    assert spill_order(spill_order(CODE, 'sweep'), 'sweep') is None


def test_the_combination_comes_first_then_each_part():
    children = variants(CODE, 'sweep')
    assert [family for family, _ in children] == list(FAMILIES)
    both = squash(children[0][1])
    assert 'bounds' not in both and both.index('void *spE4;') < both.index('void *spEC;')


def test_a_view_inside_the_array_is_left_alone():
    inside = CODE.replace('f32 lower[3];', 'f32 lower[2];')
    assert trims(inside, 'sweep') == []
    assert [family for family, _ in variants(inside, 'sweep')] == ['spill_name_order']


def test_declared_in_the_registry():
    assert any(repair.module.endswith('union_overhang_trim') for repair in registry.declared())
