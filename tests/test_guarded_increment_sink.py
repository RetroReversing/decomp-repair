from decomprepair.guarded_increment_sink import FAMILY, INLINED_FAMILY, variants

SOURCE = """extern unsigned char count;
extern unsigned int used;
extern unsigned int limit;
extern int base;
inline static unsigned int same(unsigned int arg0) { return (unsigned int) arg0; }
void f(unsigned char *arg0, int idx, int idx2)
{
  unsigned char sp23;
  unsigned char sp24;
  unsigned char sp25;
  unsigned char var_a3;
  unsigned char var_v0;
  unsigned char var_v1;
  unsigned int temp_v0_7;
  if (idx)
  {
    var_v1 = count + 1;
    if (((unsigned char) count) < 0xAU)
    {
      var_a3 = sp23;
      var_v0 = sp25;
      count = var_v1;
      use(arg0, idx, var_a3, (unsigned int) sp24, same(var_v0));
    }
  }
  else
  {
    var_v1 = count + 1;
    if (((unsigned char) count) < 0xAU)
    {
      count = var_v1;
      use(arg0, idx2, sp23, sp24, sp25);
    }
  }
  temp_v0_7 = (*((int *) (&used))) + 1;
  if (same(used) < same(limit))
  {
    used = temp_v0_7;
    base = base + (temp_v0_7 << 6);
  }
}
"""


def _found(source=SOURCE, family=None):
    return [text for fam, text in variants(source, 'f') if family in (None, fam)]


def test_every_site_is_bumped_inside_its_guard_in_one_child():
    out = _found(family=INLINED_FAMILY)[0]
    body = out[out.index('void f'):]
    assert 'count + 1' not in body and '(&used))) + 1' not in body
    assert body.count('count++;') == 2 and body.count('used++;') == 1
    assert 'base = base + (used << 6);' in body
    assert body.index('used++;') < body.index('base = base')


def test_the_inlined_child_folds_the_arms_copies_and_unwraps_identity_helpers():
    body = _found(family=INLINED_FAMILY)[0].split('void f', 1)[1]
    assert 'use(arg0, idx, sp23, (unsigned int) sp24, sp25);' in body
    assert 'var_a3 = sp23;' not in body and 'var_v0 = sp25;' not in body
    assert 'if (same(used) < same(limit))' in body  # only the arm is touched


def test_the_plain_child_keeps_the_copies():
    plain = _found(family=FAMILY)
    assert plain and all('var_a3 = sp23;' in text for text in plain)
    assert any(text.split('void f', 1)[1].count('count++;') == 2 for text in plain)


def test_single_sites_are_offered_too():
    found = _found()
    assert len(found) >= 3 and len(set(found)) == len(found)


def test_a_sum_read_after_the_guard_or_a_counter_written_again_is_left_alone():
    assert not _found(SOURCE.replace('    base = base + (temp_v0_7 << 6);\n  }\n',
                                     '    base = base + (temp_v0_7 << 6);\n  }\n  base = temp_v0_7;\n')
                      .replace('var_v1 = count + 1;', 'var_v1 = idx + 1;'))
    assert not any('used++;' in t for t in _found(SOURCE.replace('base = base + (temp_v0_7 << 6);',
                                                                   'base = base + (temp_v0_7 << 6); used = 3;')))
    assert not _found(SOURCE.replace('void f(unsigned char *arg0, int idx, int idx2)\n{\n',
                                     'void f(unsigned char *arg0, int idx, int idx2)\n{\n  int count;\n  unsigned int used;\n'))
