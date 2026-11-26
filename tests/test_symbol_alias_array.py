from decomprepair import symbol_alias_array

SOURCE = '''extern u8 flags;
extern void g(void);

void f(s32 state)
{
  u8 *q = &flags;
  switch (state) {
    case 1:
      q[0] = 0;
      q[-1] = 0x5A;
      g();
      *((s32 *) (q + 0xDE)) |= flags;
      break;
  }
}
'''


def test_the_alias_becomes_the_array():
    ((family, text),) = symbol_alias_array.variants(SOURCE, 'f')
    assert 'extern u8 flags[];' in text
    assert 'q' not in text.split('{', 1)[1]
    assert 'flags[0] = 0;\n      flags[-1] = 0x5A;' in text
    assert '(flags + 0xDE)) |= flags[0];' in text


def test_a_moved_pointer_is_left_alone():
    assert not symbol_alias_array.variants(SOURCE.replace('      g();', '      q++;'), 'f')


def test_a_symbol_other_code_names_is_left_alone():
    assert not symbol_alias_array.variants(SOURCE + 'void h(void) { flags = 1; }\n', 'f')
