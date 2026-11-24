"""Where the negation of a product by a constant sits: `e * -K`, `(-e) * K`, `-(e * K)`."""
import pytest

from decomprepair.product_negation_move import FAMILY, variants

DRAFT = '''extern s32 D_800B9ECC;
void f(void *arg0) {
    f32 temp_fv0;
    temp_fv0 = M2C_FIELD(arg0, f32 *, 8) + (f32) (D_800B9ECC * -0x14);
    M2C_FIELD(arg0, f32 *, 8) = temp_fv0;
}
'''


def _kids(text, header=None):
    return [s for fam, s in variants(text, 'f', header) if fam == FAMILY]


def test_a_product_by_a_negative_literal_moves_the_negation_onto_the_operand():
    want = DRAFT.replace('D_800B9ECC * -0x14', '(-D_800B9ECC) * 0x14')
    assert want in _kids(DRAFT)
    assert DRAFT.replace('D_800B9ECC * -0x14', '(-(D_800B9ECC * 0x14))') in _kids(DRAFT)


def test_the_negated_operand_and_the_negated_product_go_back_to_the_negative_literal():
    for spelled in ('-D_800B9ECC * 0x14', '(-D_800B9ECC) * 0x14', '-(D_800B9ECC * 0x14)', '-(0x14 * D_800B9ECC)'):
        text = DRAFT.replace('D_800B9ECC * -0x14', spelled)
        assert DRAFT in _kids(text), spelled


def test_decimal_literals_parenthesized_literals_and_a_literal_on_the_left():
    text = 'void f(s32 a, s32 *o) { o[0] = a * (-7); o[1] = -5 * (a + 1); o[2] = 3 * -a; }\n'
    kids = _kids(text)
    assert any('o[0] = (-a) * 7;' in k for k in kids)
    assert any('o[1] = (-(a + 1)) * 5;' in k for k in kids)
    assert any('o[2] = a * -3;' in k for k in kids)


def test_every_site_together_and_the_cap():
    text = 'void f(s32 a, s32 *o) { o[0] = a * -3; o[1] = a * -5; }\n'
    kids = _kids(text)
    assert any('o[0] = (-a) * 3; o[1] = (-a) * 5;' in k for k in kids)
    assert len(kids) <= 12


@pytest.mark.parametrize('text', [
    'void f(s32 a) { h(g(a) * -3); }',                       # a call is not duplicated or moved
    'void f(s32 *p, s32 i) { s32 t = (*p++) * -3; }',        # a side effect
    'void f(f32 x, f32 *o) { *o = x * -3; }',                # float
    'void f(s32 a) { f32 t = (f32) a * -3; }',               # a float cast
    'void f(s32 a, s32 b) { b = a - 3 * b; b = a * 3; }',    # a binary minus, no negation
    'void f(s32 a, s32 b) { b = b / a * -3; }',              # (b / a) * -3 is not a product of the operand
    'void f(s32 a, s32 b) { b = a * -1; b = a * -0; }',      # factor below 2
    'void f(s32 a, s32 b) { b = a * -3.0; }',                # a floating literal
    'void f(volatile s32 *p) { s32 a = (*p + 1) * -3; }',    # a volatile read
])
def test_leaves_what_it_cannot_move(text):
    assert not _kids(text)


def test_comments_and_directives_are_not_read():
    text = '#define N(x) ((x) * -3)\n/* a * -3 */\nvoid f(s32 a) { a = 1; }\n'
    assert not _kids(text)


def test_a_float_field_is_left_alone():
    assert not _kids('void f(void) { g = s.x * -3; }', header='struct S { f32 x; }; extern struct S s;')
