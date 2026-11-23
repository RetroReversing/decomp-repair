import pytest

from decomprepair import registry
from decomprepair.loop_index_inline_guard import FAMILY_BOTH, FAMILY_GUARD, FAMILY_INLINE, variants

HEADER = """extern const char names[];
extern u8 buffer[];
extern s32 gate;
extern s32 total;
"""
SOURCE = """void copy(s32 count, s32 flag) {
  s32 i;
  s32 idx;
  total = count;
  gate = 0;
  i = 0;
  if (names[0] != 0)
  {
    idx = i & 0xFF;
    do
    {
      if (flag)
      {
        i += 1;
        buffer[idx] = (u8) names[idx];
        idx = i & 0xFF;
      }
      else
      {
        i += 1;
        buffer[idx] = (u8) names[idx];
        idx = i & 0xFF;
      }
    }
    while (names[i & 0xFF] != 0);
  }
  buffer[i & 0xFF] = 0;
}"""


def test_inlines_the_index_and_moves_the_increment_after_the_stores():
    children = dict(variants(SOURCE, 'copy', HEADER))
    inlined = children[FAMILY_INLINE]
    assert 'idx' not in inlined
    assert inlined.count('buffer[i & 0xFF] = (u8) names[i & 0xFF];') == 2
    for arm in inlined.split('if (flag)')[1].split('else'):
        assert arm.index('buffer[') < arm.index('i += 1;')
    assert 'if (flag)' in inlined and 'while (names[i & 0xFF] != 0);' in inlined


def test_offers_the_guard_on_a_stored_global_and_both_together():
    children = variants(SOURCE, 'copy', HEADER)
    guards = [s for f, s in children if f == FAMILY_GUARD]
    both = [s for f, s in children if f == FAMILY_BOTH]
    assert guards and both
    assert any('if (gate)' in s for s in guards) and 'idx' in guards[0]
    assert any('if (total)' in s for s in guards)
    assert all('idx' not in s and 'if (flag)' not in s for s in both)


@pytest.mark.parametrize('source', [
    SOURCE.replace('i += 1;\n        buffer[idx] = (u8) names[idx];\n        idx = i & 0xFF;\n      }\n      else',
                   'i += 1;\n        buffer[idx] = (u8) names[idx];\n        idx = i & 0x7F;\n      }\n      else'),
    SOURCE.replace('buffer[i & 0xFF] = 0;', 'buffer[i & 0xFF] = idx;'),  # the index is read after the loop
    SOURCE.replace('        i += 1;\n        buffer[idx] = (u8) names[idx];', '        buffer[idx] = (u8) names[idx];\n        i += 1;', 1),
])
def test_refuses_other_shapes(source):
    assert variants(source, 'copy', HEADER) == []


def test_unguarded_loop_only_inlines():
    source = """void copy(s32 count) {
  s32 i;
  s32 idx;
  i = 0;
  idx = i & 0xFF;
  do
  {
    i += 1;
    buffer[idx] = (u8) names[idx];
    idx = i & 0xFF;
  }
  while (names[i & 0xFF] != 0);
  buffer[i & 0xFF] = 0;
}"""
    [(family, inlined)] = variants(source, 'copy', HEADER)
    assert family == FAMILY_INLINE
    assert 'idx' not in inlined and 'buffer[i & 0xFF] = (u8) names[i & 0xFF];\n    i += 1;' in inlined


def test_is_declared_for_the_registry():
    [repair] = [r for r in registry.declared() if r.module == 'loop_index_inline_guard']
    assert registry.problems(repair) == []
