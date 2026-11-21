"""A product's computed factor held in a local the function assigns again later."""
from decomprepair import product_operand_reuse_repairs as r

FACTOR = '((((u32) ((((T *) n)->value * 0xC00U) / 60)) * (D_1 / D_2)) >> 3)'
LOAD = '(*((u16 *) (((char *) n) + 0xFC2)))'
SOURCE = f'''void f(void)
{{
  u32 g;
  u32 h;
  s32 e;
  void *n;
  n = D_800EDA8C;
  g = {LOAD} * {FACTOR};
  e = *((s32 *) (((char *) n) + 0xF68));
  if (e != 0)
  {{
    h = *((s32 *) (((char *) n) + 0xF70)) + 5;
    *((s32 *) (((char *) n) + 0xF70)) = h & 0xFFFF;
  }}
}}
'''


def staged(source, local):
    """The variants that hold the factor in `local` (every factor here starts with two parentheses)."""
    return [t for _, t in r.variants(source, 'f') if f' {local} = ((' in t]


def test_the_factor_gets_the_later_local():
    # A sequencer function: its whole block matched the game's once the factor lived in `h`, the sum's variable.
    first, swapped = staged(SOURCE, 'h')
    assert f'  h = {FACTOR}; g = h * {LOAD};\n' in first
    assert f'  h = {FACTOR}; g = {LOAD} * h;\n' in swapped
    assert first.replace(f'h = {FACTOR}; g = h * {LOAD};', f'g = {LOAD} * {FACTOR};') == SOURCE
    # `e` is assigned again after the product too, so it is offered as well
    assert len(staged(SOURCE, 'e')) == 2


def test_the_factor_may_be_either_side():
    source = SOURCE.replace(f'g = {LOAD} * {FACTOR};', 'g = ((a + b) >> 3) * c;')
    first, swapped = staged(source, 'h')
    assert 'h = ((a + b) >> 3); g = h * c;' in first and 'h = ((a + b) >> 3); g = c * h;' in swapped


def test_left_alone_otherwise():
    # the local is read first, assigned before, or from itself
    assert staged(SOURCE.replace('  e = *', '  g = h; e = *'), 'h') == []
    assert staged(SOURCE.replace('  n = D_800EDA8C;\n', '  n = D_800EDA8C;\n  h = 0;\n'), 'h') == []
    assert staged(SOURCE.replace('h = *((s32 *) (((char *) n) + 0xF70)) + 5;', 'h = h + 5;'), 'h') == []
    # two plain factors, a sum with the product, a product that is not the whole statement, a call
    assert r.variants(SOURCE.replace(FACTOR, 'c'), 'f') == []
    assert r.variants(SOURCE.replace(FACTOR, '(c + d)').replace(f'{LOAD} * ', f'{LOAD} + '), 'f') == []
    assert r.variants(SOURCE.replace(f'g = {LOAD} * {FACTOR};', f'g = {LOAD} * {FACTOR} / 3;'), 'f') == []
    assert r.variants('void f(void) { u32 g; u32 h; g = a * b; h = 3; k(h); }', 'f') == []
