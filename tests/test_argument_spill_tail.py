"""A parameter's volatile slot, a call's shared goto tail and a call sum, together (KMC GCC 2.7.2 hypotheses)."""
from decomprepair import argument_spill_tail as r

SOURCE = '''s32 pick(void *a, f32 *b, s32 c, s32 d)
{
  volatile s32 padFC;
  volatile s32 spFC;
  s32 sp104;
  f32 best;
  f32 t;
  s32 var_a1;
  s32 hit;
  spFC = c;
  sp104 = d;
  hit = scan(a, b);
  if (hit == 1)
  {
    do { t = near(a, b); var_a1 = spFC; } while (0);
    *(f32 *) a = t;
    use(a, var_a1);
    return 1;
  }
  if (hit == 2)
  {
    t = near(a, b);
    var_a1 = spFC;
    *(f32 *) a = t;
    goto block_25;
  }
  if (d != 0)
  {
    if (check(a) != 0)
    {
      note(a, 333);
      goto block_24;
    }
    goto block_26;
  }
  return 0;
  block_24:
  var_a1 = sp104;
  block_25:
  use(a, var_a1);
  block_26:
  return 1;
}
'''
SUM = '''f32 total(f32 *p, f32 *q)
{
  f32 t;
  t = len(p, q);
  t = t + len(q, p);
  return t;
}
'''


def test_the_volatile_slot_and_its_padding_become_the_parameter():
    (family, text), = r.slot_variants(SOURCE, 'pick')
    assert family == r.SLOT_FAMILY
    assert 'volatile' not in text and 'spFC' not in text and 'sp104' not in text and 'padFC' not in text
    assert 'var_a1 = c;' in text and 'var_a1 = d;' in text


def test_a_parameter_that_is_assigned_keeps_its_slot():
    changed = SOURCE.replace('  hit = scan(a, b);', '  c = 5;\n  hit = scan(a, b);')
    (_, text), = r.slot_variants(changed, 'pick')
    assert 'spFC' in text and 'sp104' not in text


def test_each_goto_gets_the_statements_that_follow_its_label_up_to_the_return():
    texts = [text for _, text in r.tail_variants(SOURCE, 'pick')]
    all_labels = texts[0]
    assert 'goto' not in all_labels
    assert '{\nvar_a1 = sp104;\nuse(a, var_a1);\nreturn 1;\n}' in all_labels
    assert '{\nreturn 1;\n}' in all_labels
    assert len(texts) > 1                       # one rewrite per label too


def test_a_call_sum_is_one_expression():
    (family, text), = r.sum_variants(SUM, 'total')
    assert family == r.SUM_FAMILY and 't = len(p, q) + len(q, p);' in text
    assert r.sum_variants(SUM.replace('len(q, p)', 'len(t, p)'), 'total') == []


def test_the_wrapper_that_kept_a_parameter_copy_is_dropped_once_the_slot_is_gone():
    dropped = r.slot_variants(SOURCE, 'pick')[0][1]
    (family, text), = r.forward_variants(dropped, 'pick')
    assert family == r.FORWARD_FAMILY
    assert 'do {' not in text.split('if (hit == 2)')[0]
    assert 'use(a, c);\n    return 1;' in text


def test_the_chain_child_applies_every_step_and_keeps_the_function_meaning():
    found = r.variants(SOURCE, 'pick')
    chain = [text for family, text in found if family == r.FAMILY]
    best = max(chain, key=lambda text: (text.count('goto') == 0) + (text.count('volatile') == 0) * 2)
    assert 'volatile' not in best and 'goto' not in best and 'do {' not in best
    assert 'use(a, c);\n    return 1;' in best and 'use(a, var_a1);\nreturn 1;' in best
    # the steps are also offered alone
    assert {r.SLOT_FAMILY, r.TAIL_FAMILY} <= {family for family, _ in found}
    assert all(family in r.FAMILIES for family, _ in found)


def test_a_function_without_the_shapes_gets_nothing():
    assert r.variants('s32 f(s32 a)\n{\n  return a + 1;\n}\n', 'f') == []
