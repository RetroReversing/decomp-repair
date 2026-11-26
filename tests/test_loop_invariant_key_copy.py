from decomprepair.loop_invariant_key_copy import FAMILY, LOOP_ONLY, variants

SOURCE = """void f(u16 *table, u8 group)
{
  u16 head;
  u16 pos;
  u16 prev;
  u16 cur;
  head = table[0];
  pos = group;
  cur = head;
  for (;;)
  {
    if (pos >= cur)
    {
      prev = cur;
      cur = table[cur];
      if (cur != 0xFFFF)
      {
        continue;
      }
    }
    break;
  }
  table[prev] = pos;
  table[pos] = cur;
}
"""


def _by_family(source=SOURCE):
    out = {}
    for family, text in variants(source, 'f'):
        out.setdefault(family, []).append(text)
    return out


def test_the_loop_and_what_follows_it_read_a_copy_taken_at_the_loop():
    text = _by_family()[FAMILY][0]
    assert 'u16 key;' in text
    assert text.index('cur = head;') < text.index('key = pos;') < text.index('for (;;)')
    assert 'if (key >= cur)' in text and 'table[prev] = key;' in text and 'table[pos] = cur;'.replace('pos', 'key') in text


def test_the_copy_can_also_come_before_the_statement_that_precedes_the_loop():
    texts = _by_family()[FAMILY]
    assert any(text.index('key = pos;') < text.index('cur = head;') for text in texts)


def test_a_loop_only_child_leaves_the_later_reads_alone():
    text = _by_family()[LOOP_ONLY][0]
    assert 'if (key >= cur)' in text and 'table[prev] = pos;' in text and 'table[pos] = cur;' in text


def test_a_local_the_loop_writes_gets_no_copy():
    text = SOURCE.replace('prev = cur;', 'prev = cur;\n      pos = prev;')
    assert all('key = pos;' not in t for t in [x for fam in _by_family(text).values() for x in fam])


def test_a_function_without_a_loop_or_with_a_taken_address_is_left_alone():
    assert not variants('void f(u8 a)\n{\n  u16 pos;\n  pos = a;\n  g(pos);\n}\n', 'f')
    assert not variants(SOURCE.replace('pos = group;', 'pos = group;\n  h(&pos);'), 'f')


MIP_LEVELS = """void g(u32 *out, u8 *tex)
{
  s32 i;
  s32 hl;
  s32 w;
  hl = tex[0];
  w = 1 << tex[1];
  for (i = 0; i < 4; i++)
  {
    do { *out++ = (w << 9) | (hl & 0xF); } while (0);
    *out++ = w;
    hl--;
    w >>= 1;
  }
}
"""


def test_a_value_the_rest_of_the_block_writes_is_never_renamed_there():
    # A mip-level loop's inner `do { } while (0)` reads `hl`, and the outer body then steps it: renaming `hl--` to
    # the copy kept `hl` constant across the outer iterations (an unfaithful child that scored better).
    for family, text in variants(MIP_LEVELS, 'g'):
        assert '    hl--;' in text, (family, text)
        assert 'key--' not in text
