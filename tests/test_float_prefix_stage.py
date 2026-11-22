"""A float window clamp in m2c's split layout: the reused variable split, the loaded temporaries folded into their
sums, the accumulator's first sum staged, and the staged add (with the load before it) in nested one-shot scopes.

Synthetic shape of an N64 bounding-rectangle function (KMC GCC 2.7.2): a rectangle read through a pointer parameter,
offset by a record's two translations, widened by a constant, then each side the larger/smaller of that and a clamp
(`record + translation +/- margin`). From the saved best of the real function (120, 22 float-register and load-order
rows) the nested child scored 0 in the isolated judge; the staged add in one scope alone scored 50, and the rewrite
without scopes 120."""
import re

from decomprepair import float_prefix_stage as f

SOURCE = '''void clip(const void *win, const void *item)
{
  f32 dx;
  f32 dy;
  f32 lo_x;
  f32 lo_y;
  f32 hi_x;
  f32 hi_y;
  f32 box_a;
  f32 box_b;
  f32 box_c;
  f32 box_d;
  f32 m_x;
  f32 m_y;
  f32 acc;
  void *rect;
  do
  {
    dy = *((f32 *) (((char *) item) + 0x44));
  }
  while (0);
  do
  {
    if (box_a)
    {
      acc = *((f32 *) (((char *) item) + 0x38));
    }
    else
    {
      acc = *((f32 *) (((char *) item) + 0x38));
    }
  }
  while (0);
  do
  {
    rect = *((void **) (((char *) win) + 0x10));
  }
  while (0);
  {
    dx = *((f32 *) (((char *) item) + 0x40));
  }
  do
  {
    acc += dy;
  }
  while (0);
  {
    lo_x = (*((f32 *) (((char *) rect) + 0))) + dx;
  }
  do
  {
    lo_y = (*((f32 *) (((char *) rect) + 8))) + dy;
  }
  while (0);
  hi_x = (*((f32 *) (((char *) rect) + 4))) + dx;
  hi_y = (*((f32 *) (((char *) rect) + 0xC))) + dy;
  lo_x -= 8.0f;
  lo_y -= 8.0f;
  hi_x += 8.0f;
  hi_y += 8.0f;
  box_a = (*((f32 *) (((char *) item) + 0x30))) + dx;
  m_x = *((f32 *) (((char *) item) + 0x50));
  dx = (*((f32 *) (((char *) item) + 0x34))) + dx;
  m_y = *((f32 *) (((char *) item) + 0x54));
  box_a += m_x;
  acc += m_y;
  dx -= m_x;
  box_d = ((*((f32 *) (((char *) item) + 0x3C))) + dy) - m_y;
  if (lo_x < box_a)
  {
    lo_x = box_a;
  }
  if (dx < hi_x)
  {
    hi_x = dx;
  }
  if (lo_y < acc)
  {
    lo_y = acc;
  }
  if (box_d < hi_y)
  {
    hi_y = box_d;
  }
  gOut = lo_x + hi_x + lo_y + hi_y;
}
'''


def texts():
    return [text for _, text in f.variants(SOURCE, 'clip')]


def test_three_children_nested_scope_staged_add_alone_and_no_scope():
    out = texts()
    assert len(out) == 3
    nested, alone, plain = out
    assert re.search(r'do \{\n    dx = \*\(\(f32 \*\) \(\(\(char \*\) item\) \+ 0x40\)\);\n    do \{\n      acc_stage = acc_head \+ dy;\n'
                     r'    \} while \(0\);\n  \} while \(0\);', nested)
    assert re.search(r'do \{\n    acc_stage = acc_head \+ dy;\n  \} while \(0\);', alone)
    assert 'do {' not in plain.split('acc_stage')[1].split('lo_x')[0]


def test_the_sums_are_folded_at_the_position_of_their_last_add_and_the_reused_variable_is_split():
    nested = texts()[0]
    assert 'box_a = (*((f32 *) (((char *) item) + 0x30))) + dx + (*((f32 *) (((char *) item) + 0x50)));' in nested
    assert 'acc = acc_stage + (*((f32 *) (((char *) item) + 0x54)));' in nested
    assert 'dx_next = (*((f32 *) (((char *) item) + 0x34))) + dx - (*((f32 *) (((char *) item) + 0x50)));' in nested
    assert 'box_d = ((*((f32 *) (((char *) item) + 0x3C))) + dy) - (*((f32 *) (((char *) item) + 0x54)));' in nested
    assert 'if (dx_next < hi_x)' in nested and 'hi_x = dx_next;' in nested
    # the order of the folded statements is the order of the last adds: box_a, acc, dx_next, box_d
    positions = [nested.index(s) for s in ('box_a = ', 'acc = acc_stage', 'dx_next = ', 'box_d = ')]
    assert positions == sorted(positions)
    # the loaded temporaries are gone and the staged head is its own local
    assert 'm_x =' not in nested and 'm_y =' not in nested
    assert 'acc_head = *((f32 *) (((char *) item) + 0x38));' in nested
    assert 'f32 acc_head;' in nested and 'f32 acc_stage;' in nested and 'f32 dx_next;' in nested


def test_the_scaffold_arms_are_read_through_and_the_old_scopes_are_flattened():
    nested = texts()[0]
    assert 'if (box_a)' not in nested
    assert nested.count('do {') == 2


def test_m2c_field_loads_are_read_too():
    source = SOURCE
    for offset in ('0x44', '0x38', '0x40', '0x30', '0x50', '0x34', '0x54', '0x3C'):
        source = source.replace(f'*((f32 *) (((char *) item) + {offset}))', f'M2C_FIELD(item, f32 *, {offset})')
    out = [text for _, text in f.variants(source, 'clip')]
    assert out and 'acc = acc_stage + (M2C_FIELD(item, f32 *, 0x54));' in out[0]


def test_nothing_to_stage_returns_nothing():
    assert f.variants('void g(f32 *p)\n{\n  f32 a;\n  a = *p;\n  gOut = a;\n}\n', 'g') == []
    assert f.variants(SOURCE.replace('acc += m_y;', 'acc -= m_y;'), 'clip') != []  # the reuse split alone still applies


def test_a_reused_variable_read_after_a_reassignment_is_left_alone():
    source = SOURCE.replace('  gOut = lo_x', '  dx = hi_x;\n  gOut = lo_x')
    names = [text for _, text in f.variants(source, 'clip') if 'dx_next' in text]
    assert names == []
