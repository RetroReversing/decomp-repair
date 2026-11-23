"""operand_read_helper: two operand reads written as an inline helper, the join copy kept, the constant before the dispatch.

Shape of a 92-instruction KMC script-op handler (saved best 345, with a `code` copy of the index, a `value` carrier and
a one-shot loop round the first read; the match, 0, is the helper called twice, `b = 0;` before the first read, a
constant before the switch used in its second case, and one-shot wrappers on three statements)."""
import pathlib
import re

from decomprepair import operand_read_helper as w
from decomprepair import registry

SCAFFOLDED = """typedef struct
{
  s32 base;
  u32 pc;
  u8 pad[0x178];
  s16 regs[16];
} Rec;
typedef struct
{
  u32 w0;
  u32 w1;
} Op;
s32 fetch_slot();
extern s16 slot_table[];
s32 compare_op(Rec *s, register Op *c, u8 kind)
{
  s32 a;
  s32 b;
  u8 r;
  volatile u32 frame[2];
  u32 w;
  unsigned char v;
  w = c->w0;
  {
    s32 value;
    u8 code = w >> 16;
    v = w >> 16;
    do
    {
      if (0xFF & (w >> 8))
      {
        value = fetch_slot(s, code & 0xFF);
      }
      else
      {
        v &= 0x1F;
        if (v <= (16 - 1))
        {
          value = s->regs[v];
        }
        else
        {
          value = slot_table[v];
        }
      }
      a = value;
    }
    while (0);
  }
  v = c->w1;
  if ((c->w0 >> 24) != 0)
  {
    b = fetch_slot(s, v & 0xFF);
  }
  else
  {
    v &= 0x1F;
    if (v < 16)
    {
      b = s->regs[v];
    }
    else
    {
      b = slot_table[v];
    }
  }
  switch (kind)
  {
    case 0:
      r = ((s16) b) == ((s16) a);
      break;

    case 1:
      r = ((s16) a) < ((s16) b);
      break;
  }
  {
    u8 invert = ((u8 *) c)[6];
    u32 dest = c->w1;
    if (invert)
    {
      r = !r;
    }
    if (r)
    {
      s->pc = s->base + ((dest >> 16) * 8);
    }
  }
  return 0;
}
"""


def by_family(found, family):
    return [text for name, text in found if name == family]


def test_each_read_becomes_one_call_of_a_private_inline_helper():
    text = by_family(w.variants(SCAFFOLDED, 'compare_op'), w.FAMILY)[0]
    assert text.count('static __inline__ s32 read_operand(Rec *s, u8 sel, u8 idx)') == 1
    assert 'value = fetch_slot(s, idx & 0xFF);' in text and 'idx &= 0x1F;\n    if (idx < 16)' in text
    assert 'value = s->regs[idx];' in text and 'value = slot_table[idx];' in text and 'return value;' in text
    assert 'a = read_operand(s, (w >> 8) & 0xFF, w >> 16);' in text
    assert 'b = read_operand(s, c->w0 >> 24, c->w1);' in text
    assert 'code' not in text.split('compare_op(')[1] and 'do\n' not in text
    assert text.index('static __inline__') < text.index('s32 compare_op(')


def test_the_last_result_is_set_before_the_first_read_in_the_early_family():
    found = by_family(w.variants(SCAFFOLDED, 'compare_op'), w.EARLY)
    assert len(found) == 3
    last, first, both = found
    assert last.index('b = 0;') < last.index('a = read_operand(') and 'a = 0;' not in last
    assert first.index('a = 0;') < first.index('a = read_operand(') and 'b = 0;' not in first
    assert 'a = 0;' in both and 'b = 0;' in both


def test_the_constant_is_set_before_the_switch_and_its_zero_term_sits_in_its_arm():
    text = by_family(w.variants(SCAFFOLDED, 'compare_op'), w.HOIST)[0]
    assert 'u32 w;\n  unsigned char v;\n  s32 hoisted_const;' in text
    assert text.index('hoisted_const = 1;') < text.index('switch (kind)')
    assert 'r = (((s16) a) < ((s16) b)) + (hoisted_const - 1);' in text
    assert 'r = ((s16) b) == ((s16) a);' in text


def test_the_bundle_offers_the_combination_over_a_grid_of_wrappers_and_the_matching_one_is_among_them():
    found = by_family(w.variants(SCAFFOLDED, 'compare_op'), w.BUNDLE)
    plain = found[0]
    assert 'b = 0;' in plain and 'hoisted_const = 1;' in plain and 'read_operand(' in plain and 'do {' not in plain
    assert len(found) == 1 + 2 * 3 * 4 - 1
    wanted = ('do { b = read_operand(s, c->w0 >> 24, c->w1); } while (0);',
              'do { do { r = ((s16) b) == ((s16) a); } while (0); } while (0);',
              'do { do { do { s->pc = s->base + ((dest >> 16) * 8); } while (0); } while (0); } while (0);')
    assert [text for text in found if all(piece in text for piece in wanted)]


def test_another_spelling_of_the_reads_and_other_shapes_are_left_alone():
    plain = SCAFFOLDED.replace("""  {
    s32 value;
    u8 code = w >> 16;
    v = w >> 16;
    do
    {
      if (0xFF & (w >> 8))
      {
        value = fetch_slot(s, code & 0xFF);
      }
      else
      {
        v &= 0x1F;
        if (v <= (16 - 1))
        {
          value = s->regs[v];
        }
        else
        {
          value = slot_table[v];
        }
      }
      a = value;
    }
    while (0);
  }
""", """  v = w >> 16;
  if ((w >> 8) & 0xFF)
  {
    a = fetch_slot(s, v & 0xFF);
  }
  else
  {
    v &= 0x1F;
    if (v < 16)
    {
      a = s->regs[v];
    }
    else
    {
      a = slot_table[v];
    }
  }
""")
    text = by_family(w.variants(plain, 'compare_op'), w.FAMILY)[0]
    assert 'a = read_operand(s, (w >> 8) & 0xFF, w >> 16);' in text
    assert w.variants('void f(void)\n{\n    g();\n}\n', 'f') == []
    assert w.variants(SCAFFOLDED.replace('while (0);', 'while (0); goto x;', 1), 'compare_op') == []
    taken = w.variants(SCAFFOLDED + 'static __inline__ s32 read_operand(void);\n', 'compare_op')
    assert {name for name, _ in taken} == {w.HOIST}


def test_it_declares_itself_for_every_caller_lane():
    repair = registry.get('operand_read_helper')
    assert repair is not None and set(repair.families) == set(w.FAMILIES)
    assert registry.problems(repair) == []
    assert pathlib.Path(w.__file__).name == 'operand_read_helper.py' and re.search(r'^REPAIR\s*=', pathlib.Path(w.__file__).read_text(), re.M)
