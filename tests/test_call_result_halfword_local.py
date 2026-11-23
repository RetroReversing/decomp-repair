"""call_result_halfword_local: a halfword call result in a `u16` local, the other addend staged, the sum through the helper."""
from decomprepair import call_result_halfword_local as c

SOURCE = '''u16 next(void);
s32 total(u8 *p);
extern u8 table;

inline static u8 *add(s32 arg0, u8 *arg1)
{
  return arg0 + arg1;
}

inline static s32 scale(s32 arg0)
{
  return (arg0 & 0xFFFF) * 0x18;
}

void run(s32 slot, s32 now)
{
  s32 before;
  before = total(&table);
  if (before <= total(scale(slot) + ((((u16) next()) * 8) + (&table))))
  {
    now += 1;
  }
}
'''


def test_the_hoist_alone_keeps_the_sum_as_written():
    found = [text for family, text in c.variants(SOURCE, 'run') if family == c.HOIST]
    assert len(found) == 1
    assert 'temp_call = next();' in found[0] and 'u16 temp_call;' in found[0]
    assert 'if (before <= total(scale(slot) + ((temp_call * 8) + (&table))))' in found[0]


def test_the_staged_sum_through_the_inline_helper_is_one_child_with_both_argument_orders():
    found = [text for family, text in c.variants(SOURCE, 'run') if family == c.HELPER]
    assert len(found) == 2
    first = found[0]
    assert 'temp_sum = scale(slot);' in first and 'u16 temp_call;' in first and 's32 temp_sum;' in first
    assert 'total(add(((temp_call * 8) + (&table)), temp_sum))' in first
    assert 'total(add(temp_sum, ((temp_call * 8) + (&table))))' in found[1]


def test_the_plain_staged_sum_is_offered_when_there_is_no_helper():
    source = SOURCE.replace('inline static u8 *add(s32 arg0, u8 *arg1)\n{\n  return arg0 + arg1;\n}\n', '')
    families = [family for family, _ in c.variants(source, 'run')]
    assert c.STAGE in families and c.HELPER not in families


def test_a_real_call_before_the_hoisted_one_stops_the_rewrite():
    source = SOURCE.replace('if (before <= total(', 'if (total(&table) <= total(')
    assert [f for f, _ in c.variants(source, 'run')] == []


def test_a_call_in_the_body_of_an_if_is_not_hoisted_out_of_it():
    source = SOURCE.replace('  if (before <= total(scale(slot) + ((((u16) next()) * 8) + (&table))))\n  {\n    now += 1;\n  }',
                            '  if (before)\n    now = total(scale(slot) + ((((u16) next()) * 8) + (&table)));')
    assert c.variants(source, 'run') == []
