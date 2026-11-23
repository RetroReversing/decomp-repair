"""The four draft-scaffolding repairs applied together."""
import re

from decomprepair import registry
from decomprepair.draft_scaffold_combo import FAMILY, variants

CODE = '''typedef int s32;
typedef float f32;
typedef unsigned int u32;
typedef unsigned char u8;
extern void draw(s32, s32, u32);
extern void put(u32);

void f(f32 *p, void *node, s32 want)
{
  volatile struct { int unused; int filter; } stack;
#define sp14 stack.filter
  f32 fx;
  s32 ix;
  u32 word;
  u8 low;
  sp14 = want;
  fx = p[0] + p[1];
  ix = fx;
  word = *(u32 *) node;
  low = (u8) word;
  while (node != 0)
  {
    if (sp14 == 3)
    {
      low = word & 0xFF;
      draw(ix, 0, (word & 0xFF00) | ((word >> 0x18) << 0x18) | (word & (0xFF0000 & 0xFFFFu)));
      put(word & 0xFF);
    }
    node = *(void **) node;
  }
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_the_four_edits_come_as_one_child_per_order_of_the_mask_chain():
    kids = variants(CODE, 'f')
    assert {family for family, _ in kids} == {FAMILY}
    assert len(kids) == 12
    text = squash(kids[0][1])
    assert 'volatile' not in text and '#define' not in text and 'int sp14;' in text
    assert 'ix = fx;' not in text and 'draw(((s32) fx), 0,' in text
    assert 'low = word & 0xFF;' not in text and 'put(word & 0xFF)' in text
    assert '0xFFFFu' not in text


def test_one_rule_alone_is_not_a_combination():
    only = CODE.replace('ix = fx;', 'ix = 0;').replace('low = word & 0xFF;', 'low = 1;').replace('0xFF0000 & 0xFFFFu', '0xFF0000')
    assert variants(only, 'f') == []


def test_the_family_declares_itself_to_the_registry():
    [repair] = [item for item in registry.declared() if FAMILY in item.families]
    assert registry.problems(repair) == []
    assert repair.directives is True
