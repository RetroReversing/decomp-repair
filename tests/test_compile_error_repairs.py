"""Repairs a period compiler's diagnostic points at (compile_error_repairs.py)."""
from decomprepair.compile_error_repairs import diagnostics, repair

LOG = """GNU C version 2.7.2
func.c: In function `f':
func.c:7: warning: dereferencing `void *' pointer
func.c:7: invalid operands to binary +
func.c:7: invalid operands to binary +
func.c:12: called object is not a function
"""


def test_diagnostics_are_the_errors_once_each():
    assert diagnostics(LOG) == [(7, 'invalid operands to binary +'), (12, 'called object is not a function')]


def one(line, message, attempt=0):
    return repair(line, 1, message, attempt)


def test_two_pointers_added_are_read_as_integers():
    assert one('    t = M2C_FIELD(a, void ***, 8) + a;', 'invalid operands to binary +') == \
        '    t = (s32)M2C_FIELD(a, void ***, 8) + (s32)a;'


def test_the_address_of_a_function_is_one_operand_with_its_ampersand():
    out = one('    x = (&f + 0xD8) - t;', 'invalid operands to binary +')
    assert '(s32)&f + (s32)0xD8' in out


def test_the_next_attempt_takes_the_next_operator_on_the_line():
    line = '    x = a + b + c;'
    assert one(line, 'invalid operands to binary +', 0) == '    x = (s32)a + (s32)b + c;'
    assert one(line, 'invalid operands to binary +', 1) == '    x = a + (s32)b + (s32)c;'
    assert one(line, 'invalid operands to binary +', 2) is None


def test_a_compound_assignment_casts_only_its_amount():
    assert one('    *p += q;', 'invalid operands to binary +') == '    *p += (s32)q;'


def test_a_dereferenced_integer_becomes_a_word_read():
    assert one('    t = *(a + b);', "invalid type argument of `unary *'") == '    t = *(s32 *)(a + b);'
    # a star inside a cast is not an operator to repair, nor is a cast's `)` a reason to read `*` as a product
    assert one('    t = (s32) *(a + b);', "invalid type argument of `unary *'") == '    t = (s32) *(s32 *)(a + b);'
    assert one('    t = (void **)a;', "invalid type argument of `unary *'") is None


def test_a_bit_complement_of_a_pointer_is_of_its_value():
    assert one('    x = ~p;', 'wrong type argument to bit-complement') == '    x = ~(s32)p;'


def test_a_call_through_a_table_calls_the_pointer_stored_there():
    out = one('    *((i * 4) + t)(t, 1);', 'called object is not a function')
    assert out == '    ((s32 (*)()) *(s32 *)((i * 4) + t))(t, 1);'


def test_a_comment_and_other_lines_are_left_alone():
    source = 'int f(void) {\n    x = a + b; /* a + b */\n}\n'
    out = repair(source, 2, 'invalid operands to binary +')
    assert out == 'int f(void) {\n    x = (s32)a + (s32)b; /* a + b */\n}\n'
    assert repair(source, 9, 'invalid operands to binary +') is None
    assert repair(source, 2, 'something else') is None


def test_a_read_of_untyped_memory_takes_the_type_of_its_destination():
    source = '    f32 x;\n    s16 y;\n    x = *(a + b);\n    y = *(a + b);\n    z = *(a + b) << 8;\n'
    assert repair(source, 3, 'void value not ignored as it ought to be').split('\n')[2] == '    x = *(f32 *)(a + b);'
    assert repair(source, 4, 'void value not ignored as it ought to be').split('\n')[3] == '    y = *(s16 *)(a + b);'
    assert repair(source, 5, 'invalid use of void expression').split('\n')[4] == '    z = *(u8 *)(a + b) << 8;'


def test_arithmetic_on_an_incomplete_pointer_is_integer_arithmetic():
    assert one('    t = *(p + i);', 'arithmetic on pointer to an incomplete type') == '    t = *((s32)p + (s32)i);'


def test_a_float_conversion_of_a_pointer_converts_what_it_holds():
    assert one('    x = (f32) p - y;', 'pointer value used where a floating point value was expected') == \
        '    x = (f32) (s32)p - y;'


def test_a_callee_with_conflicting_argument_types_loses_its_parameter_list():
    source = 'void g(void *, void *);\nvoid f(void) {\n    g(x, 1.0f);\n}\n'
    out = repair(source, 3, "incompatible type for argument 1 of `g'")
    assert out == 'void g();\nvoid f(void) {\n    g(x, 1.0f);\n}\n'
    assert repair(out, 3, "incompatible type for argument 1 of `g'") is None
