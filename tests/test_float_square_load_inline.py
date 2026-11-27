from decomprepair import float_square_load_inline as repair

MACRO = '#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))\n'
ASM = 'lwc1 $f0, 0($a0)\nmul.s $f0, $f0, $f0\n'
SOURCE = MACRO + '''void f(void *p) {
    f32 x;
    f32 y;
    f32 sum;
    x = M2C_FIELD(p, f32 *, 0);
    y = M2C_FIELD(p, f32 *, 4);
    sum = (x * x) + (y * y);
    consume(sum);
}
'''


def test_inline_both_fields_together_and_remove_only_their_snapshots():
    out = repair.variants(SOURCE, 'f', ASM)
    assert len(out) == 1
    text = out[0][1]
    assert 'f32 x;' not in text and 'f32 y;' not in text
    assert 'sum = (M2C_FIELD(p, f32 *, 0) * M2C_FIELD(p, f32 *, 0)) +' in text
    assert 'consume(sum);' in text


def test_do_not_inline_volatile_or_reused_values_or_nonstandard_macros():
    assert repair.variants(SOURCE.replace('void *p', 'volatile void *p'), 'f', ASM) == []
    assert repair.variants(SOURCE.replace('consume(sum);', 'consume(x); consume(sum);'), 'f', ASM) == []
    assert repair.variants(SOURCE.replace(MACRO, '#define M2C_FIELD(a,b,c) change()\n'), 'f', ASM) == []
    assert repair.variants(SOURCE, 'f', 'nop\n') == []


def test_type_and_macro_must_be_nonvolatile_and_exact():
    assert repair.variants(SOURCE, 'f', ASM, 'typedef volatile float f32;') == []
    assert repair.variants(SOURCE, 'f', ASM, '#define f32 volatile float') == []
    assert repair.variants(SOURCE.replace(MACRO, MACRO.rstrip() + ' + change()\n'), 'f', ASM) == []
    assert repair.variants(SOURCE, 'f', ASM, '#undef M2C_FIELD') == []
