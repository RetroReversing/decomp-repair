"""A phantom wide block, a cast around a negated halfword, a store pair read through another pointer and a literal
argument a callee does not take: the last steps of a 131-instruction SN GCC spawn-point routine."""
from decomprepair import callee_arity_trim, negated_narrow_cast, phantom_wide_drop, record_store_swap

SOURCE = """void step(void *arg0)
{
  s32 v;
  void *made;
  { long long phantom_wide = v; }
  made = alloc(1);
  M2C_FIELD(made, s16 *, 0x6A) = 3;
  M2C_FIELD(made, void **, 0x4C) = arg0;
  M2C_FIELD(made, u8 *, 0x75) = (u8) M2C_FIELD(arg0, u8 *, 0x75);
  M2C_FIELD(arg0, s32 *, 0x20) = (s32) ((s16) -M2C_FIELD(arg0, s16 *, 0) >> 1);
}
"""


def test_phantom_block_dropped():
    [(_, text)] = phantom_wide_drop.variants(SOURCE, 'step')
    assert 'phantom' not in text and '  made = alloc(1);' in text
    assert phantom_wide_drop.variants(text, 'step') == []


def test_negated_cast_dropped():
    [(_, text)] = negated_narrow_cast.variants(SOURCE, 'step')
    assert '((-M2C_FIELD(arg0, s16 *, 0) >> 1)' not in text
    assert '(s32) (-M2C_FIELD(arg0, s16 *, 0) >> 1);' in text
    assert negated_narrow_cast.variants(SOURCE.replace('(s16) -', '(u16) -'), 'step') == []


def test_store_pair_swapped():
    children = [text for _, text in record_store_swap.variants(SOURCE, 'step')]
    assert len(children) == 1
    assert children[0].index('0x75) =') < children[0].index('0x4C) =')


def test_a_value_reading_the_other_store_stays():
    source = SOURCE.replace('(u8) M2C_FIELD(arg0, u8 *, 0x75)', '(u8) M2C_FIELD(made, u8 *, 0x4C)')
    assert record_store_swap.variants(source, 'step') == []


def test_a_literal_argument_is_trimmed():
    children = callee_arity_trim.variants(SOURCE, 'step', callees='void *alloc(void) {\n    return 0;\n}\n')
    assert any('made = alloc();' in text for _, text in children)
