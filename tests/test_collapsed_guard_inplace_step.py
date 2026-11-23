"""collapsed_guard_inplace_step: collapse the identical-arm guard, step the value in place in the arm that uses it."""
from decomprepair import collapsed_guard_inplace_step as c

SOURCE = '''s32 pick(void);
s32 limit(void);
void use(s32 v);
void note(s32 a, s32 b);

void menu(void)
{
  s32 cur;
  s32 next;
  cur = pick();
  next = cur + 1;
  do { } while (0);
  if (limit() > 3)
  {
    if (((u16) next) >= 14)
    {
      next = 13;
    }
    use(next & 0xFFFF);
  }
  else
  {
    use(limit());
  }
  if (next)
  {
    note(4, 1);
  }
  else
  {
    note(4, 1);
  }
}
'''


def test_guard_collapsed_and_the_step_moved_into_the_arm_as_one_child():
    found = [text for family, text in c.variants(SOURCE, 'menu') if family == c.COMBINED]
    assert len(found) == 1
    text = found[0]
    assert 'if (next)' not in text and 'next = cur + 1;' not in text
    assert text.count('note(4, 1);') == 1
    arm = text.split('if (limit() > 3)')[1].split('else')[0]
    assert 'cur = cur + 1;' in arm and 'if (((u16) cur) >= 14)' in arm and 'cur = 13;' in arm and 'use(cur & 0xFFFF);' in arm


def test_the_step_alone_is_refused_while_the_guard_still_reads_the_copy():
    assert [f for f, _ in c.variants(SOURCE, 'menu') if f == c.ALONE] == []


def test_the_step_alone_when_the_value_is_read_nowhere_else():
    source = SOURCE.replace('''  if (next)
  {
    note(4, 1);
  }
  else
  {
    note(4, 1);
  }
''', '')
    found = [text for family, text in c.variants(source, 'menu') if family == c.ALONE]
    assert len(found) == 1 and 'cur = cur + 1;' in found[0]


def test_nothing_when_the_stepped_value_is_read_after_the_arm():
    source = SOURCE.replace('  if (next)\n', '  use(cur);\n  if (next)\n')
    assert c.variants(source, 'menu') == []


def test_an_earlier_use_of_the_reused_copy_name_does_not_stop_the_step():
    source = SOURCE.replace('  cur = pick();\n', '  cur = pick();\n  next = cur * 3;\n  use(next);\n')
    found = [text for family, text in c.variants(source, 'menu') if family == c.COMBINED]
    assert len(found) == 1 and 'use(next);' in found[0] and 'cur = cur + 1;' in found[0]


def test_a_step_inside_a_loop_is_refused():
    source = SOURCE.replace('  next = cur + 1;\n', '  while (limit())\n  {\n  next = cur + 1;\n  }\n')
    assert c.variants(source, 'menu') == []
