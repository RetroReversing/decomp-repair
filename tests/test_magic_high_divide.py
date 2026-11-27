from decomprepair import (
    constant_term_stage,
    folded_shift_quotient,
    magic_high_divide,
    narrowed_only_local,
    shifted_factor_product,
)
from decomprepair.nested_record_view import variants as nested

DRAFT = '''s32 nextValue();
s16 aim(s32, s32);

void f(void *arg0) {
    s16 temp_s0_3;
    s32 temp_hi;
    s32 temp_s0_2;
    s32 temp_v1;
    s32 temp_s1;

    temp_v1 = M2C_FIELD(arg0, s32 *, 8) * 2 * nextValue();
    temp_hi = MULT_HI(temp_v1, 0x80010003);
    temp_s1 = ((s32) (temp_hi + temp_v1) >> 0xE) - (temp_v1 >> 0x1F);
    temp_s0_2 = aim(1, 2);
    temp_s0_3 = temp_s0_2 - ((nextValue() / 192) - 0x455);
    use(temp_s0_3, temp_s1);
}
'''


def only(module, source, *extra):
    return [text for _family, text in module.variants(source, 'f', *extra)]


def body(expression):
    return f'void f(s32 x) {{\n    s32 y;\n    y = {expression};\n    use(y);\n}}\n'


def test_signed_magic_with_its_top_bit_set():
    child = only(magic_high_divide, DRAFT)[0]
    assert 'temp_s1 = temp_v1 / 32767;' in child
    assert 'MULT_HI' not in child and 'temp_hi' not in child


def test_other_magic_shapes():
    signed = only(magic_high_divide, body('(MULT_HI(x, 0x2AAAAAAB) >> 2) - (x >> 0x1F)'))
    assert 'y = x / 24;' in signed[0]
    unsigned = only(magic_high_divide, body('(u32) MULTU_HI(x, 0xCCCCCCCD) >> 3'))
    assert 'y = (u32) x / 10;' in unsigned[0]
    wide = only(magic_high_divide, body('(((u32) (x - MULTU_HI(x, 0x24924925)) >> 1) + MULTU_HI(x, 0x24924925)) >> 2'))
    assert 'y = (u32) x / 7;' in wide[0]
    # a high word that is no division stays
    assert only(magic_high_divide, body('MULTU_HI(x, 0x12345) >> 2')) == []


def test_shift_before_the_division():
    asm = 'sra $v1, $v0, 3\nmult $v1, $a0\nsra $v0, $v0, 31\n'
    assert ['(nextValue() >> 3) / 24' in text for text in only(folded_shift_quotient, DRAFT, asm)] == [True]
    # without the assembly, every split of the divisor
    assert len(only(folded_shift_quotient, body('x / 192'))) == 6


def test_shifted_factor():
    child = only(shifted_factor_product, DRAFT)[0]
    assert '(M2C_FIELD(arg0, s32 *, 8) << 1) * nextValue();' in child


def test_local_read_only_into_a_narrow_variable():
    children = only(narrowed_only_local, DRAFT)
    assert len(children) == 1 and 's16 temp_s0_2;' in children[0]
    assert only(narrowed_only_local, DRAFT.replace('temp_s0_2 - ', 'temp_s0_2 / ')) == []


def test_nested_record_view_survives_a_term_it_cannot_read():
    source = 'void f(s32 a, s32 b, s32 c) {\n    s32 x;\n    x = a * b * c;\n    g(x);\n}\n'
    assert nested(source, 'f') == []


def test_bracketed_constant_term_gets_its_own_local():
    child = only(constant_term_stage, DRAFT)[0]
    assert 's32 term;' in child
    assert 'term = (nextValue() / 192) - 0x455;' in child and 'temp_s0_3 = temp_s0_2 - term;' in child
    assert only(constant_term_stage, body('x - (x * 4)')) == []


def test_shifted_factor_operand_forms():
    for operand in ('x', 'p->size', 'rows[i]', '(a + b)', 'next(x)', 'M2C_FIELD(p, s32 *, 8)'):
        assert f'y = ({operand} << 2) * x;' in only(shifted_factor_product, body(f'{operand} * 4 * x'))[0]
