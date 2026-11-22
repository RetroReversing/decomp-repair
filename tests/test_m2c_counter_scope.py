"""m2c's own macros no longer disable the loop-weight families, a counter stepped by a literal stride is a counter,
and the reused-name split and the weighted start can be offered together; the preheader run is reordered."""
from decomprepair import loop_weight_repairs as w
from decomprepair import preheader_run_order, reused_counter_split_scope
from decomprepair.equal_value_flow import macros_safe

PRELUDE = """#ifndef M2C_DEFINES
#define M2C_DEFINES
#define M2C_FIELD(expr, type_ptr, offset) (((struct { __typeof__(*(type_ptr)0) v; } *)((s8 *)(expr) + (offset)))->v)
#define M2C_ERROR(desc) (0)
#endif
"""

SOURCE = PRELUDE + """
void walk(void *arg0, s32 mode, s32 *out) {
    s32 var_s6;
    s32 n;
    s32 *list;
    char *base;
    s32 buf;
    s32 var_a1;
    s32 temp;
    switch (mode) {
    case 3:
        n = M2C_FIELD(arg0, s8 *, 0x9F);
        var_s6 = (n * 3) + 2;
        out[0] = var_s6;
        out[1] = var_s6 + n;
        break;
    }
    temp = M2C_FIELD(arg0, s32 *, 0x10);
    if (temp >= 0) {
        base = &buf;
        var_a1 = temp;
        var_s6 = 0;
        do {
            out[var_a1] = M2C_FIELD(arg0, s32 *, 4) + var_s6;
            var_a1 += 0x20;
            var_s6 += 0xC;
        } while (var_a1 < 0x100);
    }
}
"""


def test_m2c_prelude_macros_are_read_only_expressions():
    assert macros_safe(SOURCE, '', SOURCE, {'var_s6'})
    assert not macros_safe('#define HIDE(x) do { x = 1; } while (0)\nvoid f(){ HIDE(a); }', '', 'HIDE(a);', set())


def test_a_literal_stride_counter_start_is_wrapped_even_with_m2c_macros():
    out = [text for _, text in w.variants(SOURCE, 'walk')]
    assert any('/*__repair_loop_weight*/do { var_s6 = 0; } while (0);' in text for text in out)


def test_split_and_weighted_start_come_as_one_candidate():
    result = reused_counter_split_scope.variants(SOURCE, 'walk')
    assert result and all(family == reused_counter_split_scope.FAMILY for family, _ in result)
    text = result[0][1]
    assert '/*__repair_loop_weight*/do { var_s6_b1 = 0; } while (0);' in text
    assert 'var_s6 = (n * 3) + 2;' in text and 'var_s6_b1 += 0xC;' in text
    assert reused_counter_split_scope.variants(text, 'walk') == []


def test_the_setup_run_before_a_loop_is_permuted():
    result = [t for _, t in preheader_run_order.variants(SOURCE, 'walk')]
    assert len(result) == 5
    assert all(t != SOURCE for t in result)
    assert any(t.index('var_a1 = temp;') > t.index('var_s6 = 0;') for t in result)
    assert any(t.index('base = &buf;') > t.index('var_a1 = temp;') for t in result)
    assert preheader_run_order.variants(SOURCE.replace('var_s6 = 0;', 'var_s6 = var_a1;'), 'walk') == []
    assert preheader_run_order.variants(SOURCE.replace('var_a1 = temp;', 'var_a1 = temp;\n        var_a1 = 1;'), 'walk') == []
