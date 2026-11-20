from decomprepair.near_match_repairs import bitwise_operand_order, square_rootf


def test_square_rootf_requires_one_explicit_float_declaration_and_call():
    source = 'extern float sqrt(float);\nfloat f(float x) { return sqrt(x); }'
    assert square_rootf(source, 'f') == source.replace('sqrt(', 'sqrtf(')
    assert square_rootf(source.replace('float', 'double'), 'f') is None
    assert square_rootf(source, 'f', '#define sqrt(x) (x)') is None
    assert square_rootf(source.replace('sqrt(x)', 'sqrt(sqrt(x))'), 'f') is None


def test_bitwise_order_keeps_simple_local_values():
    source = 'unsigned f(unsigned x) { unsigned a = x; unsigned b = 7; a &= b; return a; }'
    assert [child for _, child in bitwise_operand_order(source, 'f')] == [
        source.replace('a &= b;', 'a = b & a;'),
        source.replace('a &= b;', 'a = a & b;'),
    ]
    assert not bitwise_operand_order(source.replace('unsigned b', 'volatile unsigned b'), 'f')
    assert not bitwise_operand_order(source, 'f', '#define b foo()')
