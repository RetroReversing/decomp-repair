"""A product by a small constant written as the sum of the operand and the rest of the product."""
import pytest

from decomprepair.product_split_sum import FAMILY, variants

DRAFT = '''extern s32 D_8010788C;
extern s32 D_80107890;
void f(s32 arg0, s32 arg1) {
    s32 temp_a1;
    D_8010788C = arg0;
    temp_a1 = (((arg1 - 0x12) / 10) * 0xD) + 0x12;
    D_80107890 = temp_a1;
}
'''
Q = '((arg1 - 0x12) / 10)'


def _kids(text, header=None):
    return [s for fam, s in variants(text, 'f', header) if fam == FAMILY]


def test_the_quotient_product_becomes_quotient_plus_rest():
    want = DRAFT.replace(f'({Q} * 0xD)', f'({Q} + ({Q} * 0xC))')
    assert want in _kids(DRAFT)
    assert DRAFT.replace(f'({Q} * 0xD)', f'(({Q} * 0xC) + {Q})') in _kids(DRAFT)


def test_the_match_spelling_is_the_same_tree():
    # the saved match reads `Q + (Q * 0xC) + 0x12`; the child is `(Q + (Q * 0xC)) + 0x12`, the same left-leaning sum
    assert f'({Q} + ({Q} * 0xC)) + 0x12' in _kids(DRAFT)[0]


def test_decimal_factor_and_constant_on_the_left():
    text = 'void f(s32 a, s32 *d) { d[0] = a * 7; d[1] = 5 * (a + 1); }\n'
    kids = _kids(text)
    assert 'd[0] = a + (a * 6);' in kids[0]
    assert any('d[1] = (a + 1) + ((a + 1) * 4);' in k for k in kids)


@pytest.mark.parametrize('text', [
    'void f(s32 a) { h(f2(a) * 3); }',          # a call is not duplicated
    'void f(s32 *p, s32 i) { s32 t = (*p++) * 3; }',      # a side effect
    'void f(f32 x, f32 *o) { *o = x * 3; }',              # float: 3x is not x + 2x
    'void f(s32 a, s32 b) { b = b / a * 3; }',            # a / b * 3 groups as (b / a) * 3
    'void f(s32 *p, s32 a) { a = *p * 3; }',              # unary deref
    'void f(s32 a) { a *= 3; a = a * 1; a = a * 100; }',  # compound assignment, factor 1, factor beyond the bound
    'void f(volatile s32 *p) { s32 a = (*p + 1) * 3; }',  # a volatile read is not duplicated
])
def test_leaves_what_it_cannot_duplicate(text):
    assert not _kids(text)


def test_every_site_together_and_the_cap():
    text = 'void f(s32 a, s32 *o) { o[0] = a * 3; o[1] = a * 5; }\n'
    kids = _kids(text)
    assert 'o[0] = a + (a * 2); o[1] = a + (a * 4);' in kids[-1]
    assert len(kids) <= 16


def test_a_float_field_is_left_alone():
    header = 'typedef struct { f32 scale; s32 n; } S;\n'
    text = 'void f(S *s, s32 *o) { o[0] = s->n * 3; o[1] = (s32) (s->scale * 3); }\n'
    kids = _kids(text, header)
    assert any('o[0] = s->n + (s->n * 2);' in k for k in kids)
    assert not any('scale + ' in k for k in kids)


def test_a_cast_stays_with_its_operand():
    text = 'void f(s32 a, s32 *o) { *o = (s16) (a >> 2) * 3; }\n'
    assert '*o = (s16) (a >> 2) + ((s16) (a >> 2) * 2);' in _kids(text)[0]
