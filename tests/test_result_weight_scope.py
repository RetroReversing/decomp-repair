"""A call's result assignment, or its guarded `if`, in a one-shot scope (a 1300-instruction routine, 65 -> 0)."""
from decomprepair.result_weight_scope import FAMILY, REPAIR, variants

SOURCE = """void steer(Obj *o, s16 m)
{
  f32 x;
  f32 y;
  x = 0.0f;
  if ((m != 2) & (m != 5))
  {
    x = getAxis(o, 0x19, 0x1A);
  }
  y = getAxis(o, 8, 9);
  use(x, y);
}
"""


def squash(text):
    return ' '.join(text.split())


def test_the_guarded_if_comes_first_then_each_assignment():
    found = [squash(text) for family, text in variants(SOURCE, 'steer') if family == FAMILY]
    assert len(found) == 3
    assert 'do { if ((m != 2) & (m != 5)) { x = getAxis(o, 0x19, 0x1A); } } while (0);' in found[0]
    assert any('{ do { x = getAxis(o, 0x19, 0x1A); } while (0); }' in text for text in found[1:])
    assert any('do { y = getAxis(o, 8, 9); } while (0); use(x, y);' in text for text in found[1:])


def test_an_if_with_an_else_is_not_wrapped_whole():
    source = SOURCE.replace('    x = getAxis(o, 0x19, 0x1A);\n  }\n', '    x = getAxis(o, 0x19, 0x1A);\n  }\n  else\n  {\n    x = 1.0f;\n  }\n')
    found = [squash(text) for family, text in variants(source, 'steer')]
    assert all('do { if (' not in text for text in found)


def test_a_store_through_a_pointer_is_not_read():
    assert variants(SOURCE.replace('y = getAxis(o, 8, 9);', 'o->y = getAxis(o, 8, 9);'), 'steer')[-1][1].count('do') == 1


def test_it_declares_itself():
    assert REPAIR['variants'] is variants and REPAIR['families'] == (FAMILY,)
