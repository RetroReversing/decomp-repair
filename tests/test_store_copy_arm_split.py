import re

from decomprepair.store_copy_arm_split import FAMILIES, FAMILY, PLAIN, POINTER, REPAIR, variants

SOURCE = """
void decode(void)
{
  u8 *buf;
  u8 pad[12];
  s32 n;
  s8 *src;
  s8 *base;
  u8 *addr;
  u8 old;
  u8 cur;
  base = table();
  src = base;
  n = 0;
  buf = pad;
  pad[0] = *src;
  cur = *src;
  if (cur != 0)
  {
    do
    {
      addr = buf + n;
      old = *addr;
      src += 1;
      n += 1;
      do
      {
        *addr = old - 1; cur = *src;
      }
      while (0);
      buf[(unsigned char) n] = cur;
    }
    while (cur != 0);
  }
  finish(pad, n, base);
}
"""


def by_family(source=SOURCE):
    found = {}
    for family, text in variants(source, 'decode'):
        found.setdefault(family, []).append(text)
    return found


def test_it_declares_itself_for_the_registry():
    assert REPAIR['families'] == FAMILIES == (FAMILY, PLAIN)
    assert REPAIR['needs'] == ('source', 'name')


def test_the_store_becomes_a_copy_and_an_add_in_two_identical_arms():
    text = by_family()[PLAIN][0]
    assert f'u8 *{POINTER};' in text
    assert f'{POINTER} = buf;\n      if (' in text
    assert f'{{ {POINTER} += n; }} else {{ {POINTER} += n; }}\n      *{POINTER} = cur;' in text
    assert '(unsigned char)' not in text


def test_the_guard_is_a_local_the_loop_does_not_assign_and_the_longest_lived_first():
    guards = [re.search(r'if \((\w+)\) \{ q_as', text)[1] for text in by_family()[PLAIN]]
    assert guards[0] == 'base'
    assert 'n' not in guards and 'src' not in guards and 'cur' not in guards and 'old' not in guards


def test_the_combination_scopes_the_address_the_copy_and_splits_the_store_scope_in_one_child():
    texts = by_family()[FAMILY]
    child = next(t for t in texts if f'do {{ do {{ {POINTER} = buf; }} while (0); }} while (0);' in t
                 and 'do { addr = buf + n; } while (0);' in t)
    assert 'do { *addr = old - 1; } while (0); cur = *src;' in child
    assert f'*{POINTER} = cur;' in child
    assert any('do { do { addr = buf + n; } while (0); } while (0);' in t for t in texts)


def test_a_store_outside_a_loop_is_left_alone():
    outside = SOURCE.replace('    while (cur != 0);\n  }\n', '    while (cur != 0);\n  }\n  buf[(unsigned char) n] = cur;\n')
    flat = outside.replace('do\n    {', 'if (cur)\n    {').replace('    while (cur != 0);', '    ')
    assert variants(flat.replace('buf[(unsigned char) n] = cur;\n    ', ''), 'decode') == []


def test_it_does_not_rewrite_its_own_output_or_a_store_of_a_float():
    for _, text in variants(SOURCE, 'decode'):
        assert variants(text, 'decode') == []
    assert variants(SOURCE.replace('u8 old;', 'f32 old;').replace('u8 cur;', 'f32 cur;'), 'decode') == []
    assert variants(SOURCE, 'missing') == []
