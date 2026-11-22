"""product_shift_hoist and accumulator_chain across statements (a 719-instruction KMC N64 function).

Rebuilt from its match: the accumulator's shift written back into the product after an `if` (1280), and the first link
through a temporary with the record's next two loads between (205); both together 2120. product_shift_hoist then gives
205 and the widened accumulator_chain 0."""
from decomprepair import accumulator_chain_repairs as chain
from decomprepair import product_shift_stage_repairs as stage

HOIST = '''void f(char *p, s16 *t)
{
  s32 acc;
  s32 a;
  s32 k;
  acc = *((s32 *) (p - 0x92));
  acc = (acc >> 7) * t[1];
  a = *((s32 *) (p - 0x8A));
  k = 0x348;
  if (p[3] != 0)
  {
    k = 0x370;
  }
  acc = (acc >> 7) * t[k];
  g(acc, a);
}
'''


def test_the_plain_stage_goes_right_after_the_last_write():
    hoisted = [text for family, text in stage.variants(HOIST, 'f') if family == 'product_shift_hoist']
    want = ('  acc = (acc >> 7) * t[1];\n  shift_stage = acc >> 7;\n  a = *((s32 *) (p - 0x8A));')
    assert any(want in text and 'acc = shift_stage * t[k];' in text and 'while (0)' not in text for text in hoisted)


def test_no_hoist_past_a_block_that_writes_the_value():
    text = HOIST.replace('    k = 0x370;\n', '    k = 0x370;\n    acc = 0;\n')
    hoisted = [t for family, t in stage.variants(text, 'f') if family == 'product_shift_hoist']
    assert not any('acc = shift_stage * t[k];' in t for t in hoisted)


CHAIN = '''void f(char *p, s16 *t)
{
  s32 acc;
  s32 tmp;
  s32 a;
  u8 b;
  tmp = ((*((s32 *) (p - 0x92))) >> 7);
  a = *((s32 *) (p - 0x8A));
  b = *((u8 *) (p - 0x78));
  acc = tmp * t[1];
  acc = (acc >> 7) * t[2];
  g(acc, a, b);
}
'''


def test_the_chain_folds_across_independent_loads():
    found = [text for _, text in chain.variants(CHAIN, 'f')]
    assert any('  acc = *((s32 *) (p - 0x92));\n  acc = (acc >> 7) * t[1];\n  a = *' in text for text in found)
    assert any('  acc = *((s32 *) (p - 0x92));\n  a = *' in text and 'b = *((u8 *) (p - 0x78));\n  acc = (acc >> 7) * t[1];'
               in text for text in found)


def test_no_fold_when_a_statement_between_uses_the_temporary_or_calls():
    assert chain.variants(CHAIN.replace('a = *((s32 *) (p - 0x8A));', 'a = tmp;'), 'f') == []
    assert chain.variants(CHAIN.replace('a = *((s32 *) (p - 0x8A));', 'a = h();'), 'f') == []
