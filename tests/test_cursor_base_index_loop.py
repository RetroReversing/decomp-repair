"""A cursor stepped beside the loop counter, written as a base indexed by the counter."""
from decomprepair import registry
from decomprepair.cursor_base_index_loop import FAMILY, FOR_FAMILY, variants

SOURCE = """void walk(u8 *p, s32 *out, s32 mode)
{
  u8 *q;
  u32 i;
  u8 x;
  u8 y;
  q = p + 2;
  i = 0;
  if (p[1]) do {
    x = q[0];
    y = q[1];
    if (mode) {
      out[0] += x;
      out[1] += y;
    } else {
      ++*out;
    }
    ++i;
    q += 3;
  } while (i < p[1]);
  q = p + 8;
}
"""


def test_the_cursor_becomes_a_base_indexed_by_the_counter():
    children = dict((family, child) for family, child in variants(SOURCE, 'walk'))
    child = children[FAMILY]
    assert 'x = q[i * 3];' in child and 'y = q[i * 3 + 1];' in child
    assert 'q += 3;' not in child
    assert 'q = p + 2;' in child and 'i = 0;' in child and 'if (p[1]) do {' in child


def test_the_guarded_do_also_comes_as_the_for_loop_the_game_had():
    child = dict(variants(SOURCE, 'walk'))[FOR_FAMILY]
    assert 'for (i = 0; i < p[1]; i++) {' in child
    assert 'i = 0;\n  if' not in child and '++i;' not in child
    assert 'x = q[i * 3];' in child and 'while (i < p[1])' not in child


def test_a_cursor_read_after_the_loop_or_in_any_other_way_is_declined():
    assert variants(SOURCE.replace('q = p + 8;', 'out[2] = q[0];'), 'walk') == []
    assert variants(SOURCE.replace('y = q[1];', 'y = *q;'), 'walk') == []
    assert variants(SOURCE.replace('++i;\n    q += 3;', 'q += 3;\n    ++i;\n    q += 3;'), 'walk') == []
    assert variants(SOURCE.replace('x = q[0];', 'if (mode) continue;\n    x = q[0];'), 'walk') == []
    assert variants(SOURCE.replace('i = 0;', 'i = 1;'), 'walk') == []


def test_a_step_of_one_and_a_parenthesised_cursor_are_indexed_too():
    source = SOURCE.replace('x = q[0];', 'x = ((q))[0];').replace('q += 3;', 'q += 1;')
    child = dict(variants(source, 'walk'))[FAMILY]
    assert 'x = q[i];' in child and 'y = q[i + 1];' in child


def test_registry_declares_the_families():
    repair = registry.get('cursor_base_index_loop')
    assert repair is not None and registry.problems(repair) == []
    assert FAMILY in repair.families and FOR_FAMILY in repair.families
