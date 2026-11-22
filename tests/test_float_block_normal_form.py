"""A run of m2c float assignments written as the game's source had it: unfenced, one local per value, folded."""
from decomprepair import float_block_normal_form as r
from decomprepair import registry

# A bounding-box clamp: a clip rectangle intersected with an outer one (KMC GCC 2.7.2, 96 instructions). The saved best
# was m2c's spelling with the permuter's fences and guards and stood at 120, register rows only; the normal form of
# the run, with nothing else changed, was the game's (0).
SOURCE = '''extern s32 gOn;
extern void *gCursor;
void clip(const void *outer, const void *box)
{
  f32 off;
  f32 off_2;
  f32 oy;
  f32 lo;
  f32 hi;
  f32 add_a;
  f32 add_b;
  f32 top;
  f32 left;
  f32 right;
  f32 bottom;
  void *temp_a1;
  void *rect;
  do
  {
    oy = *((f32 *) (((char *) box) + 0x64));
  }
  while (0);
  do
  {
    if (left)
    {
      top = *((f32 *) (((char *) box) + 0x58));
    }
    else
    {
      top = *((f32 *) (((char *) box) + 0x58));
    }
  }
  while (0);
  rect = *((void **) (((char *) outer) + 0x20));
  {
    off = *((f32 *) (((char *) box) + 0x60));
  }
  do
  {
    top += oy;
  }
  while (0);
  left = (*((f32 *) (((char *) rect) + 0))) + off;
  right = (*((f32 *) (((char *) rect) + 4))) + off;
  left -= 8.0f;
  right += 8.0f;
  lo = (*((f32 *) (((char *) box) + 0x50))) + off;
  add_a = *((f32 *) (((char *) box) + 0x70));
  off = (*((f32 *) (((char *) box) + 0x54))) + off;
  add_b = *((f32 *) (((char *) box) + 0x74));
  lo += add_a;
  top += add_b;
  off -= add_a;
  hi = ((*((f32 *) (((char *) box) + 0x5C))) + oy) - add_b;
  if (left < lo)
  {
    left = lo;
  }
  if (off < right)
  {
    if (oy)
    {
      right = off;
    }
    else
    {
      right = off;
    }
  }
  if (gOn != 0)
  {
    temp_a1 = gCursor;
    gCursor = temp_a1 + 8;
    *((s32 *) temp_a1) = (s32) (left * 4.0f) + (s32) (top * 4.0f) + (s32) (hi * 4.0f);
  }
}
'''


def offered(source=SOURCE, name='clip'):
    return [text for label, text in r.variants(source, name) if label == r.FAMILY]


def test_the_whole_normal_form_is_one_child():
    (child,) = offered()
    assert 'while (0)' not in child and 'do\n' not in child
    assert 'if (left)' not in child and 'if (oy)' not in child
    # the offset that held two values is two locals, the sums are folded, the twice-updated one is split in two
    assert 'off_a = *((f32 *) (((char *) box) + 0x60));' in child
    assert 'lo = ((*((f32 *) (((char *) box) + 0x50))) + off_a) + add_a;' in child
    assert 'top_a = (*((f32 *) (((char *) box) + 0x58))) + oy;' in child
    assert child.index('top_a = ') < child.index('top = top_a + add_b;') and 'top += ' not in child
    assert 'off = ((*((f32 *) (((char *) box) + 0x54))) + off_a) - add_a;' in child
    assert 'f32 off_a;' in child and 'f32 top_a;' in child
    # literal updates stay in place; the clamps after the run are untouched
    assert 'left -= 8.0f;' in child and 'right += 8.0f;' in child
    assert '    right = off;\n' in child and 'if (off < right)' in child


def test_the_child_is_the_same_program_for_every_original_local():
    (child,) = offered()
    before = [line for line in SOURCE.splitlines()]
    assert len(child.splitlines()) < len(before)
    # the final value of each original local, by the module's own check, is unchanged: it offers nothing otherwise
    assert r.variants(child, 'clip') == []


def test_a_value_read_between_its_updates_is_not_folded():
    source = SOURCE.replace('  lo += add_a;\n', '  lo += add_a;\n  hi = lo;\n').replace(
        '  top += add_b;\n', '  top += add_b;\n  oy = top;\n')
    # `hi = lo` reads lo after its last update (fine), `oy = top` reads top after both (fine): still folded ...
    assert 'top_a = ' in offered(source)[0]
    # ... but a read between the two updates of `top` keeps its two updates as they are
    between = SOURCE.replace('  lo = (*((f32 *) (((char *) box) + 0x50))) + off;\n',
                             '  lo = (*((f32 *) (((char *) box) + 0x50))) + off;\n  hi = top;\n')
    (child,) = offered(between)
    assert 'top += oy;' in child and 'top += add_b;' in child and 'top_a' not in child


def test_a_function_that_calls_or_stores_in_the_run_is_left_alone():
    source = SOURCE.replace('  left -= 8.0f;\n', '  g(left);\n  left -= 8.0f;\n')
    (child,) = offered(source)
    assert 'g(left);' in child and 'off_a' not in child  # the run ends at the call: nothing before it is a web pair
    assert r.variants('void h(void)\n{\n  g();\n}\n', 'h') == []


def test_a_plain_run_with_nothing_to_normalise_offers_nothing():
    source = 'void p(const void *a)\n{\n  f32 x;\n  x = *((f32 *) (((char *) a) + 4));\n  if (x < 1.0f)\n  {\n    x = 1.0f;\n  }\n}\n'
    assert r.variants(source, 'p') == []


def test_declarator_lists_and_pointer_locals_are_read():
    source = SOURCE.replace('  f32 off;\n  f32 off_2;\n  f32 oy;\n', '  f32 off, off_2, oy;\n')
    (child,) = offered(source)
    assert 'f32 off, off_2, oy;' in child and 'f32 off_a;' in child


def test_it_declares_itself_to_the_registry():
    repair = registry.get('float_block_normal_form')
    assert repair and registry.problems(repair) == [] and repair.needs == ('source', 'name')
