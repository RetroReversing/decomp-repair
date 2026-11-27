from decomprepair import copyback_float_negation as copyback
from decomprepair import float_literal_local_stage as literal
from decomprepair import inline_reused_float_expression as inline
from decomprepair import staged_float_negation as staged

ASM = 'c.lt.s $f0, $f4\nbc1t .L1\nmov.s $f6, $f4\nneg.s $f6, $f4\n'
HEADER = '#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))'


def test_negation_repairs_reject_float_names_shadowed_with_another_type():
    old = '''void f(void) {
    f32 x;
    f32 y;
    { int x;
        if (x > 0.0f) { y = x; } else { y = -x; }
        x = y;
    }
}
'''
    assert not copyback.variants(old, 'f', ASM)
    assert not staged.variants(old.replace('if (x > 0.0f) { y = x; } else { y = -x; }',
                                           'y = -x; if (x > 0.0f) { y = x; }'), 'f', ASM)


def test_literal_and_expression_repairs_reject_shadows():
    source = '''void f(void) {
    f32 x;
    f32 y;
    { int x;
        y = (x * 3.14f) / 180.0f;
    }
}
'''
    assert not literal.variants(source, 'f')
    expression = '''void f(char *p) {
    f32 x;
    { int x;
        x = M2C_FIELD(p, f32 *, 4) * 2.0f;
        M2C_FIELD(p, f32 *, 8) = x + 1.0f;
    }
}
'''
    assert not inline.variants(expression, 'f', HEADER)
