import re

from decomprepair import registry
from decomprepair.join_copy_arm_anchor import FAMILY, SINK_FAMILY, variants

SOURCE = """void tick(void *obj)
{
  s32 near;
  s32 force;
  s32 slot;
  u8 mode;
  mode = *(u8 *) ((u8 *) obj + 4);
  force = 0;
  switch (mode)
  {
    case 0:
      goto joined;
    case 1:
      if (!probe(1)) { return; }
      force = 1;
      goto joined;
    case 2:
      if (probe(2) == 3) { return; }
      goto check;
    case 4:
      force = 1;
      if (!(*(u8 *) ((u8 *) obj + 8))) { return; }
      goto joined;
    case 5:
      force = 1;
      if (*(s8 *) ((u8 *) obj + 9) != 41) { return; }
      goto joined;
  }
  joined:
  check:
  near = force;
  if (!near && !(dist(obj) < 3.0f)) { return; }
  slot = 0;
  use(obj, slot);
}
"""


def _flat(text):
    return re.sub(r'\s+', ' ', text)


def _by_family(source=SOURCE):
    out = {}
    for family, text in variants(source, 'tick'):
        out.setdefault(family, []).append(_flat(text))
    return out


def test_the_arm_that_skips_the_copy_makes_it_and_the_label_moves_behind_it():
    child = _by_family()[FAMILY][0]
    assert 'near = force; goto check;' in child
    assert re.search(r'joined: near = force; check: if \(!near', child)
    # the flag stores stay where they were: this child is the anchor alone
    assert 'force = 1; if (!(*(u8 *) ((u8 *) obj + 8))) { return; }' in child


def test_the_flag_stores_follow_their_return_guards_in_the_combined_child():
    child = _by_family()[SINK_FAMILY][0]
    assert 'near = force; goto check;' in child
    assert 'if (!(*(u8 *) ((u8 *) obj + 8))) { return; } force = 1; goto joined;' in child
    assert 'if (*(s8 *) ((u8 *) obj + 9) != 41) { return; } force = 1; goto joined;' in child
    # the store that already followed its guard is left alone, and every path still stores the flag once
    assert child.count('force = 1;') == 3
    assert 'force = 0;' in child


def test_a_guard_that_reads_the_flag_or_has_an_else_keeps_its_store():
    reads = SOURCE.replace('if (!(*(u8 *) ((u8 *) obj + 8))) { return; }', 'if (force == 0) { return; }')
    child = _by_family(reads)[SINK_FAMILY][0]
    assert 'force = 1; if (force == 0) { return; } goto joined;' in child


def test_a_global_flag_is_not_moved_past_a_guard_that_returns():
    source = SOURCE.replace('  s32 force;\n', '').replace('void tick', 'extern s32 force;\nvoid tick')
    assert SINK_FAMILY not in _by_family(source)


def test_a_goto_in_an_unbraced_if_is_not_given_a_copy():
    source = SOURCE.replace('      goto check;', '      if (mode) goto check;')
    assert _by_family(source) == {}


def test_no_labels_no_children():
    assert variants('void f(void) { s32 a; s32 b; b = a; }', 'f') == []


def test_the_module_declares_itself_for_the_app():
    repair = {r.module: r for r in registry.declared()}['join_copy_arm_anchor']
    assert set(repair.families) == {FAMILY, SINK_FAMILY}
    assert repair.needs == ('source', 'name')
