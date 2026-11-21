"""The one-shot initializer scope before a guard: proposals only, nothing is compiled here."""
import re

from decomprepair.branch_slot_scope import variants

# The shape of a timer-update loop (GCC 2.7.2, KMC, N64) stuck at 10: the target filled the guard's delay slot with
# the inner counter's `= 0`, after both volatile loads, ahead of the two register copies.
BEFORE = '''extern s32 D_800C0788;
extern s32 D_800C078C;
void f(s32 arg0)
{
  s32 slot;
  u32 count;
  u32 i;
  s32 saved;
  slot = arg0 << 4;
  count = *((volatile u32 *) (slot + ((u32) (&D_800C078C))));
  saved = slot;
  if (count != 0)
  {
    i = 0;
    do
    {
      i += 1;
    }
    while (i < (*((volatile u32 *) (saved + ((u32) (&D_800C0788))))));
  }
}
'''
MATCHED_SHAPE = '''  count = *((volatile u32 *) (slot + ((u32) (&D_800C078C))));
  do {
      i = 0;
  } while (0);
  if (count != 0)
  {
    saved = slot;
    do
'''


def _all(text, name='f'):
    return [src for fam, src in variants(text, name) if fam == 'branch_slot_scope']


def _squash(text):
    return re.sub(r'\s+', ' ', text)


def test_the_matched_shape_is_one_of_the_proposals():
    assert any(_squash(MATCHED_SHAPE) in _squash(src) for src in _all(BEFORE))


def test_the_bare_hoist_is_proposed_too():
    bare = [src for src in _all(BEFORE) if 'saved = slot;\n  do {' in src or _squash('saved = slot; do {') in _squash(src)]
    assert bare and all('while (0);' in src for src in _all(BEFORE))


def test_nothing_is_proposed_when_the_variable_lives_on_after_the_guard():
    after = BEFORE.replace('  }\n}\n', '  }\n  slot = i;\n}\n')
    assert _all(after) == []


def test_nothing_is_proposed_when_the_guard_reads_the_variable():
    assert _all(BEFORE.replace('if (count != 0)', 'if (i != 0)')) == []


def test_a_copy_the_guard_reads_stays_before_it():
    guarded = BEFORE.replace('if (count != 0)', 'if (saved != 0)')
    assert _all(guarded)
    assert all('if (saved != 0) { saved = slot;' not in _squash(src) for src in _all(guarded))


def test_only_mips_is_proposed():
    assert variants(BEFORE, 'f', arch='ppc') == []
