"""One labelled zero return that the other zero exits jump to (KMC GCC 2.7.2 cross-jumping, a hypothesis)."""
from decomprepair import zero_exit_label_repairs as r

SOURCE = '''s32 seg(void *p, void *q)
{
  f32 d;
  s32 bit;
  s32 low;
  s32 high;
  s32 fail;
  bit = 0;
  d = *(f32 *) p - *(f32 *) q;
  if (d > 0.0f)
  {
    if (!(d < 1.0f))
    {
      if (*(f32 *) q < d)
      {
        return 0;
      }
      goto inner;
    }
    return bit;
  }
  fail = 0;
  if ((!(d < 2.0f)) && (!(d > 3.0f)))
  {
    inner:
    low = d > 4.0f;
    high = bit;
    if ((low | high) != 0)
    {
      return 0;
    }
    if (!(low | high))
      goto done;
    return bit;
    done:;
    return 1;
  }
  return fail;
}
'''


def texts(source=SOURCE):
    return [text for family, text in r.variants(source, 'seg') if family == r.FAMILY]


def test_the_final_guarded_return_becomes_the_label():
    first = texts()[0]
    assert '__zero_exit:\n    return 0;\n    done:;' in first
    assert first.count('return bit;') == 1  # only the early one is kept
    assert 'goto __zero_exit;' not in first


def test_each_part_of_the_chain_is_offered_alone_and_together():
    found = texts()
    assert len(found) == 4
    with_later = [t for t in found if 'return fail;' not in t]
    with_guards = [t for t in found if 'if (!(*(f32 *) q < d)) goto inner;' in t]
    assert len(with_later) == 2 and len(with_guards) == 2
    both = [t for t in with_later if t in with_guards]
    assert len(both) == 1
    assert both[0].count('goto __zero_exit;') == 2
    assert 'if (!(*(f32 *) q < d)) goto inner;\n    goto __zero_exit;' in both[0]


def test_a_final_return_that_is_not_known_to_be_zero_is_left_alone():
    source = SOURCE.replace('high = bit;', 'high = low;')
    assert texts(source) == []


def test_the_zero_literal_is_enough_and_one_label_is_never_added_twice():
    source = SOURCE.replace('return bit;\n    done:;', 'return 0;\n    done:;')
    assert texts(source)
    assert r.variants(texts(source)[0], 'seg') == []


def test_a_function_without_the_shape_has_no_variants():
    assert r.variants('s32 f(s32 a) {\n    return a;\n}\n', 'f') == []
    assert r.variants(SOURCE, 'missing') == []
