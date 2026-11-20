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


def test_float_update_stages_the_measurement_once():
    from decomprepair.near_match_repairs import float_update_order

    load = 'M2C_FIELD(obj, f32 *, 0x40)'
    source = f'void f(void *obj) {{ {load} = (compute({load}) * 0.5f) + {load}; }}'
    variants = dict(float_update_order(source, 'f'))
    assert set(variants) == {'arithmetic_operand_order', 'float_update_lifetime'}
    assert 'float repair_float_increment = (compute(' in variants['float_update_lifetime']
    assert all(child.count('compute(') == 1 for child in variants.values())
    assert not float_update_order(source.replace('f32', 's32'), 'f')
