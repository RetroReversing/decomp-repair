from decomprepair.selected_argument_call_split import FAMILY, variants

SOURCE = """void f(u8 *arg0, u8 *spare, s32 flags)
{
  u8 *var_a0;
  s32 idx;
  s32 sp29;
  var_a0 = arg0;
  if (flags & 0x1000)
  {
    var_a0 = spare;
  }
  idx = find(var_a0, &sp29, 1);
  use(idx, sp29);
}
"""


def _found(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_the_call_is_written_in_both_arms_with_each_choice():
    found = _found()
    assert len(found) == 1
    out = found[0]
    assert 'var_a0 =' not in out
    assert out.index('idx = find(spare, &sp29, 1);') < out.index('else') < out.index('idx = find(arg0, &sp29, 1);')
    assert 'if (flags & 0x1000)' in out


def test_a_local_read_elsewhere_or_named_twice_in_the_call_is_left_alone():
    assert not _found(SOURCE.replace('  use(idx, sp29);', '  use(idx, var_a0);'))
    assert not _found(SOURCE.replace('find(var_a0, &sp29, 1)', 'find(var_a0, var_a0, 1)'))


WRAPPED = """void g(u8 *p, u8 *q, s32 *o)
{
  s32 w;
  s32 idx;
  w = 0x10;
  if (o[0] == 0 && *(s32 *)(p + 8) == 0x20)
  {
    w = 0x20;
  }
  do { load(w, q, 0, 0); } while (0);
  idx = next();
  w = idx;
  idx += 4;
  done(idx - w);
}
"""


def test_a_one_shot_wrapper_and_a_later_web_of_the_local_are_taken():
    """A billboard drawer (SN64 GCC 2.8.1): the pick in `do { } while (0)` and `w` reused for a copy later (250 -> 10)."""
    [out] = [text for family, text in variants(WRAPPED, 'g') if family == FAMILY]
    assert 'do {' not in out and 'while (0)' not in out
    assert out.index('load(0x20, q, 0, 0);') < out.index('else') < out.index('load(0x10, q, 0, 0);')
    assert 'w = 0x10' not in out and 'w = idx;' in out and 'done(idx - w);' in out


def test_a_later_read_of_the_pick_is_left_alone():
    assert not variants(WRAPPED.replace('  w = idx;\n', ''), 'g')
    assert not variants(WRAPPED.replace('  w = idx;\n', '  w = w + idx;\n'), 'g')
    assert not variants(WRAPPED.replace('  w = idx;\n', '  if (idx) { w = idx; }\n'), 'g')


def test_plain_assignments_between_the_pick_and_the_call_stay_ahead_of_it():
    source = WRAPPED.replace('  do { load', '  s = 0x7C0;\n  t = s;\n  do { load')
    [out] = [text for family, text in variants(source, 'g') if family == FAMILY]
    assert out.index('s = 0x7C0;') < out.index('t = s;') < out.index('if (o[0] == 0') < out.index('load(0x20')
    assert not variants(source.replace('t = s;', 'o = s;'), 'g')  # it changes what the pick's test reads
    assert not variants(source.replace('t = s;', 't = w;'), 'g')


def test_the_later_copy_is_also_offered_above_its_early_return_guard():
    source = WRAPPED.replace('  idx = next();\n  w = idx;\n', '  idx = next();\n  if (idx == -1)\n  {\n    return;\n  }\n  w = idx;\n')
    found = [text for family, text in variants(source, 'g') if family == FAMILY]
    assert len(found) == 2
    assert '  idx = next();\n  w = idx;\n  if (idx == -1)' in found[1] and 'load(0x20, q, 0, 0);' in found[1]
