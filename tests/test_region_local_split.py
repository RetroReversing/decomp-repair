"""One scratch local reused by two unrelated goto ladders, given a name per ladder."""
import re

from decomprepair.region_local_split import variants

SOURCE = '''void f(int sel, int t, s16 *out)
{
  s16 mode;
  int other;
  switch (sel)
  {
    case 1:
      if (t == 4) { goto four; }
      goto dflt;
      four:
      mode = 4;
      goto save;
      dflt:
      mode = 1;
      save:
      *out = mode;
      return;

    case 2:
      if (t < 3) { goto low; }
      mode = 9;
      goto done;
      low:
      mode = 2;
      done:
      *out = mode + 1;
      return;

    default:
      return;
  }
}
'''


def _squash(text):
    return re.sub(r'\s+', ' ', text)


def _all(source=SOURCE):
    return [_squash(text) for family, text in variants(source, 'f') if family == 'region_local_split']


def test_the_second_region_gets_its_own_local():
    found = _all()
    assert found
    text = found[0]
    assert 's16 mode; s16 mode_2;' in text
    assert '*out = mode; return;' in text and '*out = mode_2 + 1;' in text
    assert 'mode_2 = 9;' in text and 'mode_2 = 2;' in text and 'mode = 4;' in text


def test_a_read_before_any_assignment_in_a_region_declines():
    source = SOURCE.replace('      if (t < 3) { goto low; }\n', '      if (mode < 3) { goto low; }\n')
    assert _all(source) == []


def test_a_goto_into_a_region_from_outside_keeps_that_region_as_it_was():
    source = SOURCE.replace('      goto dflt;\n', '      goto low;\n')
    assert _all(source) == []


def test_an_address_taken_local_and_a_function_without_a_switch_decline():
    source = SOURCE.replace('*out = mode;', 'g(&mode);')
    assert _all(source) == []
    assert variants('void f(int a)\n{\n  int x;\n  x = a;\n  g(x);\n}\n', 'f') == []
