from decomprepair import (
    accumulator_chain_repairs,
    clamp_default_scope_repairs,
    default_else_repairs,
    disjoint_local_merge_repairs,
    guard_temp_sink_repairs,
    loop_entry_reset_repairs,
    loop_head_giv_repairs,
    narrow_count_copy_repairs,
    product_shift_stage_repairs,
    reused_temp_split_repairs,
    stored_compare_repairs,
    volatile_local_drop_repairs,
)
from decomprepair.propose import propose

LOOP = '''void f(void)
{
  u8 *p;
  u8 *q;
  s32 i;

  p = &tbl;
  i = 0;
  q = p + 0xC2;
  do
  {
    g(q);
    i += 1;
    p += 0x1A0;
    q = p + 0xC2;
  }
  while (i < 4);
}
'''


def test_derived_pointer_moves_to_the_loop_head():
    [(family, out)] = loop_head_giv_repairs.variants(LOOP, 'f')
    assert family == 'loop_head_pointer_giv'
    assert '  i = 0;\n  do\n  {\n    q = p + 0xC2;\n    g(q);' in out
    assert out.count('q = p + 0xC2;') == 1


def test_derived_pointer_stays_when_the_tail_differs():
    assert loop_head_giv_repairs.variants(LOOP.replace('q = p + 0xC2;\n  }', 'q = p + 0xC4;\n  }'), 'f') == []


DEFAULT = '''void f(int c)
{
  s32 a;

  a = 0;
  if (c != 0)
  {
    a = g();
  }
  h(a);
}
'''


def test_default_moves_into_an_else_arm():
    # default_into_then (0.5.605) also offers the inverted-test form of the same move, so the
    # input has two variants; this test is about the else-arm one.
    found = dict(default_else_repairs.variants(DEFAULT, 'f'))
    assert set(found) == {'default_into_else', 'default_into_then'}
    out = found['default_into_else']
    assert '  if (c != 0)\n  {\n    a = g();\n  }\n  else\n  {\n    a = 0;\n  }\n  h(a);' in out
    assert 'a = 0;\n  if' not in out


def test_default_stays_when_the_body_reads_it_first():
    assert default_else_repairs.variants(DEFAULT.replace('a = g();', 'a = a + g();'), 'f') == []


def test_else_default_moves_back_in_front_of_its_if():
    one = default_else_repairs.variants(DEFAULT, 'f')[0][1]
    found = dict(default_else_repairs.variants(one, 'f'))
    assert 'else_into_default' in found
    out = found['else_into_default']
    assert out == DEFAULT


COMPARE = '''void f(u32 a, u32 x)
{
  u32 t;

  t = a + g();
  *((u32 *) (((char *) p) + 0x2E)) = t;
  if (((a < x) && (t < x)) || ((x < a) && (x < t)))
  {
    h();
  }
}
'''


def test_condition_tests_the_stored_memory():
    [(family, out)] = stored_compare_repairs.variants(COMPARE, 'f')
    assert family == 'stored_value_compare'
    assert 'if (((a < x) && ((*((u32 *) (((char *) p) + 0x2E))) < x)) || ((x < a) && (x < (*((u32 *) (((char *) p) + 0x2E))))))' in out
    assert out.count('= t;') == 1


COUNT = '''extern u8 count;
void f(void)
{
  s32 i;

  i = 0;
  if (((s32) count) > 0)
  {
    g(i);
  }
}
'''


def test_narrow_count_is_copied_into_a_signed_local():
    [(family, out)] = narrow_count_copy_repairs.variants(COUNT, 'f')
    assert family == 'narrow_count_copy'
    assert '  s32 i;\n  s32 count_count;' in out
    assert '  count_count = count;\n  if (count_count > 0)' in out


def test_wide_counts_are_left_alone():
    assert narrow_count_copy_repairs.variants(COUNT.replace('u8', 's32'), 'f') == []


RESET = '''void f(s32 n)
{
  s32 i;
  s32 o;

  i = 0;
  if (n > 0)
  {
    do
    {
      g(i);
      i += 1;
    }
    while (i < n);
    i = 0;
  }
  o = 0;
  do
  {
    h(o);
    i += 1;
    o = i * 0x28;
  }
  while (i < 0x20);
}
'''


def test_counter_is_reset_before_the_second_loop():
    [(family, out)] = loop_entry_reset_repairs.variants(RESET, 'f')
    assert family == 'loop_entry_counter_reset'
    assert '  }\n  i = 0;\n  o = 0;\n  do' in out


SINK = '''void f(s32 x)
{
  s32 t;

  t = x - 0x2000;
  if (x != 0x2000)
  {
    g(t);
  }
}
'''


def test_temporary_moves_into_the_if_that_uses_it():
    [(family, out)] = guard_temp_sink_repairs.variants(SINK, 'f')
    assert family == 'guard_temp_sink'
    assert '  if (x != 0x2000)\n  {\n    t = x - 0x2000;\n    g(t);' in out


def test_temporary_stays_when_read_after_the_if():
    assert guard_temp_sink_repairs.variants(SINK.replace('  }\n}', '  }\n  h(t);\n}'), 'f') == []


SHIFT = '''void f(s32 v)
{
  s32 d;

  d = g() - (h() * (v >> 8));
}
'''


def test_shift_feeding_a_product_is_staged_in_a_scope():
    [(family, out)] = product_shift_stage_repairs.variants(SHIFT, 'f')
    assert family == 'product_shift_stage'
    assert '  s32 shift_stage;' in out
    assert '  do\n  {\n    shift_stage = v >> 8;\n  }\n  while (0);\n  d = g() - (h() * shift_stage);' in out


CLAMP = '''void f(s32 x)
{
  s32 v;

  if (x >= 0)
  {
    v = 0x7F0000;
    if (x <= 0x7F0000)
    {
      v = x;
    }
  }
  else
  {
    v = 0;
  }
  g(v);
}
'''


def test_clamp_default_is_scoped():
    [(family, out)] = clamp_default_scope_repairs.variants(CLAMP, 'f')
    assert family == 'clamp_default_scope'
    assert '    do\n    {\n      v = 0x7F0000;\n    }\n    while (0);\n    if (x <= 0x7F0000)' in out


def test_clamp_default_is_scoped_when_the_body_starts_with_another_statement():
    src = CLAMP.replace('      v = x;', '      { long long pad = 0; }\n      v = x;')
    [(family, out)] = clamp_default_scope_repairs.variants(src, 'f')
    assert family == 'clamp_default_scope'
    assert 'v = 0x7F0000;\n    }\n    while (0);' in out


VOLATILE = '''void f(void)
{
  volatile unsigned int t;
  s32 a;

  a = 1;
  g(a);
}
'''


def test_volatile_local_loses_its_qualifier():
    [(family, out)] = volatile_local_drop_repairs.variants(VOLATILE, 'f')
    assert family == 'volatile_local_drop'
    assert '  unsigned int t;\n' in out and 'volatile' not in out


MERGE = '''void f(void)
{
  s32 i;
  s32 j;
  s32 k;

  i = 0;
  g(i);
  j = 2;
  h(j);
  k = 3;
  h(k);
}
'''


def test_disjoint_locals_are_merged():
    out = [t for _, t in disjoint_local_merge_repairs.variants(MERGE, 'f')]
    assert any('s32 j;' not in t and 'i = 2;' in t and 'h(i);' in t for t in out)
    assert all('  s32 i;' in t for t in out)


def test_locals_alive_together_are_not_merged():
    src = MERGE.replace('  h(j);\n', '  h(j);\n  g(i);\n')
    out = [t for _, t in disjoint_local_merge_repairs.variants(src, 'f')]
    assert not any('s32 j;' not in t and 'i = 2;' in t for t in out)


CHAIN = '''void f(void)
{
  s32 t;
  s32 acc;

  t = ((*((s32 *) (((char *) p) + (-0x92)))) >> 7);
  acc = t * (*((s16 *) q));
  acc = (acc >> 7) * (*((s16 *) r));
  g(acc);
}
'''


def test_temporary_is_folded_into_the_accumulator():
    [(family, out)] = accumulator_chain_repairs.variants(CHAIN, 'f')
    assert family == 'accumulator_chain'
    assert '  acc = *((s32 *) (((char *) p) + (-0x92)));\n  acc = (acc >> 7) * (*((s16 *) q));\n  acc = (acc >> 7)' in out


SPLIT = '''void f(s32 a)
{
  s32 t;

  t = a >> 7;
  g(t);
  t = h() - 1;
  g(t);
}
'''


def test_reused_temporary_is_split():
    out = [t for _, t in reused_temp_split_repairs.variants(SPLIT, 'f')]
    assert any('s32 t_b1;' in t and 't_b1 = h() - 1;' in t and 'g(t_b1);' in t and 'g(t);' in t for t in out)


def test_every_family_runs_through_propose():
    report = propose(LOOP, 'f', header='')
    assert not [t for t in report.timings if t.error]


def test_reused_temporary_split_chooses_an_unused_name():
    source = SPLIT.replace('  s32 t;', '  s32 t;\n  s32 t_b1;\n  s32 t_b1_;')
    [(family, candidate)] = reused_temp_split_repairs.variants(source, 'f')
    assert family == 'reused_temp_split'
    assert candidate == (source.replace('  s32 t;', '  s32 t;\n  s32 t_b1__;')
                         .replace('  t = h() - 1;\n  g(t);', '  t_b1__ = h() - 1;\n  g(t_b1__);'))


def test_reused_temporary_split_keeps_assignments_feeding_switch_join():
    source = '''void f(s32 which)
{
  s32 value;
  switch (which) {
  case 0:
    value = 0;
    break;
  case 1:
    value = h();
    break;
  default:
    value = 2;
    break;
  }
  g(value);
}
'''
    assert not any('value_b1 = h();' in text for _, text in reused_temp_split_repairs.variants(source, 'f'))


def test_reused_temporary_restores_orphaned_switch_write():
    source = '''void f(s32 which)
{
  s32 value;
  s32 value_b1_;
  switch ((u32)which) {
  case 0:
    value = 0;
    break;
  case 1:
    value_b1_ = h();
    break;
  default:
    value = 2;
    break;
  }
  g(value);
}
'''
    family = reused_temp_split_repairs.RESTORE_FAMILY

    def restores(text):
        return [candidate for label, candidate in reused_temp_split_repairs.variants(text, 'f') if label == family]

    assert restores(source) == [source.replace('s32 value_b1_;', '').replace('value_b1_ = h();', 'value = h();')]
    assert not restores(source.replace('value_b1_ = h();', 'value_b1_ = h();\n    g(value_b1_);'))
    assert not restores(source.replace('g(value);', 'value = h();\n  g(value);'))
    assert not restores(source.replace('value = 0;', 'g(0);').replace('value = 2;', 'g(2);'))
