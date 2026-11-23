from decomprepair import flag_web_narrow as r

# a loop flag (0, then 1, tested with `!flag`) whose name m2c reuses after the loop for a length
REUSED = '''extern s32 total;
extern void *table[];
extern void step(void *);
extern void emit(s32);

void f(void)
{
  register s32 flag;
  s32 i;
  flag = 0;
  i = 0;
  do
  {
    if (table[i] != NULL)
    {
      step(table[i]);
      flag = 1;
    }
    else
      if (!flag)
    {
      emit(i);
    }
    i += 1;
  }
  while (i < 6);
  flag = total - i;
  emit(flag);
}
'''

ALONE = '''extern void step(void);

void g(void)
{
  s32 flag;
  s32 i;
  flag = 0;
  i = 0;
  do
  {
    if (flag == 0)
    {
      flag = 1;
    }
    step();
    i += 1;
  }
  while (i < 4);
}
'''


def test_the_reused_flag_is_split_and_narrowed_in_one_child():
    out = [text for fam, text in r.variants(REUSED, 'f') if fam == 'flag_web_narrow']
    assert out
    child = out[0]
    assert 'register s8 flag_1;' in child and 'register s32 flag_2;' in child
    assert 'flag_1 = 1;' in child and '!flag_1' in child
    assert 'flag_2 = total - i;' in child and 'emit(flag_2);' in child
    # no wide value reaches the byte
    assert 'flag_1 = total' not in child


# the same, with a `goto` in the loop: the web that holds the loop keeps the original name
KEPT = REUSED.replace('      emit(i);\n    }\n    i += 1;', '      emit(i);\n    }\n    if (i == 3)\n    {\n      goto next;\n    }\n    next:\n    i += 1;')


def test_the_name_the_flag_kept_is_narrowed():
    out = [text for fam, text in r.variants(KEPT, 'f')]
    assert any('register s8 flag;' in t and 'flag_1 = total - i;' in t for t in out), out


def test_the_split_alone_or_the_type_alone_is_not_the_child():
    for fam, text in r.variants(REUSED, 'f'):
        assert 's8 flag_1' in text and 'flag_2 = total' in text


def test_a_flag_with_no_other_web_is_narrowed_alone():
    out = [text for fam, text in r.variants(ALONE, 'g')]
    assert any('s8 flag;' in t for t in out)


def test_a_wide_value_in_the_name_is_left_alone():
    source = REUSED.replace('flag = 1;', 'flag = total;')
    assert not r.variants(source, 'f')


def test_an_address_taken_flag_is_left_alone():
    source = REUSED.replace('emit(flag);', 'step(&flag);')
    assert not any('s8 flag;' in t for _, t in r.variants(source, 'f'))
