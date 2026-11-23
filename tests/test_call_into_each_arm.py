"""call_into_each_arm: a call after an `if`/`else` chain written at the end of each arm.

Synthetic shape of a 795-instruction KMC object spawner (1615 -> 745): the arms set the call's arguments, and the game's
two identical `jal`s were cross-jumped into one, each arm setting its own argument registers."""
from decomprepair import call_into_each_arm as s

SOURCE = '''void *spawn(s16 id, void *obj) {
  s32 a1;
  s32 t;
  u8 a3;
  s32 k;
  setup(obj);
  if (gBorder != 0) {
    k = id & 0xFFFF;
    t = look(k);
    a3 = row(k);
    a1 = t;
  } else {
    switch (gMode) {
      default:
        a1 = 0x11;
        break;
      case 25:
        a1 = 0x10;
        break;
    }
    a3 = 0;
  }
  start(obj, a1, 1, a3);
  finish(obj, 0x159);
  return obj;
}
'''


def _texts(source=SOURCE):
    return [text for family, text in s.variants(source, 'spawn') if family == s.FAMILY]


def test_the_call_is_written_at_the_end_of_both_arms_and_removed_from_the_join():
    [text] = _texts()
    assert text.count('start(obj, a1, 1, a3);') == 2
    assert '    a1 = t;\n    start(obj, a1, 1, a3);\n  } else {' in text
    assert '    a3 = 0;\n    start(obj, a1, 1, a3);\n  }\n  finish(obj, 0x159);' in text


def test_an_arm_that_returns_does_not_get_the_call():
    source = SOURCE.replace('    a3 = 0;\n', '    a3 = 0;\n    return obj;\n')
    [text] = _texts(source)
    assert text.count('start(obj, a1, 1, a3);') == 1


def test_arguments_no_arm_sets_make_no_child():
    source = SOURCE.replace('start(obj, a1, 1, a3);', 'start(obj, id, 1, 2);')
    assert _texts(source) == []


def test_an_if_without_else_makes_no_child():
    source = '''void f(s32 v) {
  s32 a;
  if (v) {
    a = 1;
  }
  g(a);
}
'''
    assert s.variants(source, 'f') == []


def test_an_else_if_chain_gets_the_call_in_every_arm():
    source = '''void f(s32 v) {
  s32 a;
  if (v == 1) {
    a = 1;
  } else if (v == 2) {
    a = 2;
  } else {
    a = 3;
  }
  g(a, 7);
}
'''
    [text] = [t for _, t in s.variants(source, 'f')]
    assert text.count('g(a, 7);') == 3 and text.rstrip().endswith('}')
