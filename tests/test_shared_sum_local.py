"""shared_sum_local: one local for a sum a block computes three times.

Synthetic shape of a 795-instruction KMC object spawner (4325 -> 4030): `y0 + 1` written three times, once inside
`dy + (y0 + 1)`, which cse reassociates; named once before its first use it is the target's single add."""
from decomprepair import shared_sum_local as s

SOURCE = '''void f(void *p, void *q) {
  s32 y0, dy;
  y0 = 5;
  dy = 6;
  if (p != NULL) {
    put(p, 0x22, y0 + 1);
    put(q, 0x22, dy + (y0 + 1));
    mark(q);
    r = y0 + 1;
  }
}
'''


def _texts(source=SOURCE):
    return [text for family, text in s.variants(source, 'f') if family == s.FAMILY]


def test_the_sum_is_named_before_its_first_use_and_replaces_all_three():
    source = SOURCE.replace('put(p, 0x22, y0 + 1);', 'a = y0 + 1;')
    [text] = _texts(source)
    assert '  s32 y0_sum;\n' in text
    assert '    y0_sum = y0 + 1;\n    a = y0_sum;' in text
    assert 'dy + y0_sum' in text and 'r = y0_sum;' in text


def test_a_sum_inside_a_larger_expression_is_not_replaced():
    source = SOURCE.replace('put(p, 0x22, y0 + 1);', 'a = y0 + 1;').replace('r = y0 + 1;', 'r = 3 * y0 + 1;')
    assert _texts(source) == []


def test_an_assignment_in_between_stops_the_rewrite():
    source = SOURCE.replace('put(p, 0x22, y0 + 1);', 'a = y0 + 1;').replace('    mark(q);', '    y0 = 9;')
    assert _texts(source) == []


def test_two_uses_are_not_enough_and_floats_are_left_alone():
    source = SOURCE.replace('    r = y0 + 1;\n', '')
    assert _texts(source) == []
    floats = SOURCE.replace('s32 y0, dy;', 'f32 y0, dy;').replace('put(p, 0x22, y0 + 1);', 'a = y0 + 1;')
    assert _texts(floats) == []
