"""A condition's loaded value repeated in an arm, held in a local set before the `if`."""
import re

from decomprepair.condition_value_local import variants

BEFORE = '''void f(u16 i)
{
  if (rows[i].alpha + 8 >= 0xFFU) {
    rows[i].alpha = 0xFF;
  } else {
    rows[i].alpha = rows[i].alpha + 8;
  }
}
'''


def _squash(text):
    return re.sub(r'\s+', ' ', text)


def test_the_compared_value_is_held_in_a_local():
    found = [_squash(src) for _, src in variants(BEFORE, 'f')]
    assert found[0] == ('void f(u16 i) { { u32 compared = rows[i].alpha + 8; if (compared >= 0xFFU) { rows[i].alpha = 0xFF; } '
                        'else { rows[i].alpha = compared; } } } ')
    assert any('s32 compared = rows[i].alpha + 8;' in text for text in found)


def test_the_arm_may_be_the_first_one():
    source = 'void f(int *p) { if ((p->x + 1) < 10) { p->x = p->x + 1; } else { p->x = 0; } }'
    found = [src for _, src in variants(source, 'f')]
    assert 'void f(int *p) { { u32 compared = p->x + 1; if (compared < 10) { p->x = compared; } else { p->x = 0; } } }' in found


def test_calls_plain_locals_and_other_stores_are_left_alone():
    assert not variants('void f(int *p) { if (g(p) < 10) { *p = g(p); } }', 'f')
    assert not variants('void f(int a, int *p) { if (a + 1 < 10) { *p = a + 1; } }', 'f')
    assert not variants('void f(int *p) { if (p->x < 10) { p->y = 0; p->x = p->x; } }', 'f')
    assert not variants('void f(int *p) { if (p->x < p->y) { p->y = p->x; } }', 'f')
