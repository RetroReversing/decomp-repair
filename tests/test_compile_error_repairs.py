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


def test_a_call_to_itself_converts_the_argument_to_the_parameters_type():
    source = 'void f(void *a, s32 b) {\n    f(x, y);\n}\n'
    once = repair(source, 2, "incompatible type for argument 1 of `f'")
    assert once == 'void f(void *a, s32 b) {\n    f((void *)(s32)x, y);\n}\n'
    twice = repair(once, 2, "incompatible type for argument 2 of `f'")
    assert twice == 'void f(void *a, s32 b) {\n    f((void *)(s32)x, (s32)y);\n}\n'
    assert repair(source, 2, "incompatible type for argument 3 of `f'") is None


def test_compact_drops_comments_and_indentation_only():
    from decomprepair.compile_error_repairs import compact
    source = 'void f(void) {\n    case 1:   /* switch 1 */\n        x = a  + b; \n\n\n\n}\n'
    assert compact(source) == 'void f(void) {\ncase 1:\nx = a  + b;\n\n}\n'
    assert compact('x;\n') is None


IDO_LOG = """cfe: Warning 709: func.c, line 5: Incompatible pointer type assignment
 x = y;
 ----^
cfe: Error: func.c, line 69: Unacceptable operand of == or !=
     } while (var_s1 != &arg0);
 -------------------^
cfe: Error: func.c, line 21: Unacceptable operand of '+'.
     g(arg0 + 4);
 ---------^
cfe: Error: func.c, line 26: Bad operand type for += or -=
         var_v1 += 8;
 ---------------^
cfe: Error: func.c, line 24: Dereferenced a non-pointer.
     *(arg0 | 4) = 1;
 -----------^
cfe: Error: func.c, line 9: Syntax Error
"""


def test_ido_errors_are_read_as_the_repairs_words():
    assert diagnostics(IDO_LOG) == [(69, 'invalid operands to binary =='), (21, 'invalid operands to binary +'),
                                    (26, 'invalid operands to binary +='), (24, "invalid type argument of `unary *'")]


def test_an_ido_pointer_compare_is_read_as_integers():
    assert one('    } while (var_s1 != &arg0);', 'invalid operands to binary ==') == '    } while ((s32)var_s1 != (s32)&arg0);'
    assert one('    if (a == b) {}', 'invalid operands to binary ==') == '    if ((s32)a == (s32)b) {}'


def test_an_ido_compound_assignment_casts_its_amount():
    assert one('    var_v1 += 8;', 'invalid operands to binary +=') == '    var_v1 += (s32)8;'
    assert one('    var_v1 -= p;', 'invalid operands to binary +=') == '    var_v1 -= (s32)p;'


def test_sn64_names_its_preprocessed_file():
    log = "func.sn.i: In function `f':\nfunc.sn.i:257: pointer value used where a floating point value was expected\nfunc.sn.i:9: warning: x\n"
    assert diagnostics(log) == [(0, 'pointer value used where a floating point value was expected')]


def test_ido_float_and_pointer_casts_go_through_an_integer():
    line = '    func_80000000(0.0f, ((f32)( &D_21B20)) , arg0 + 4, ((M2C_UNK *)( arg3)) , 0.0f);'
    assert diagnostics('cfe: Error: func.c, line 3: Cast a pointer into a non-integral type.\n') == [(3, 'ido: pointer cast to a float')]
    assert one(line, 'ido: pointer cast to a float') == \
        '    func_80000000(0.0f, ((f32)(s32)( &D_21B20)) , arg0 + 4, ((M2C_UNK *)( arg3)) , 0.0f);'
    assert one(line, 'ido: float cast to a pointer') == \
        '    func_80000000(0.0f, ((f32)( &D_21B20)) , arg0 + 4, ((M2C_UNK *)(s32)( arg3)) , 0.0f);'
    assert one(line, 'ido: pointer cast to a float', 1) is None


def test_a_call_through_a_typed_table_read_keeps_its_cast():
    out = one('    *(s32 *)((D_1 * 4) + &D_2)(arg0, v);', 'called object is not a function')
    assert out == '    ((s32 (*)()) *(s32 *)((D_1 * 4) + &D_2))(arg0, v);'


def test_a_call_that_disagrees_with_the_guessed_prototype_drops_its_parameters():
    src = 'M2C_UNK g(void *, s32);\nvoid f(void) {\n    g(1);\n}\n'
    out = repair(src, 3, 'too few arguments to function')
    assert out.startswith('M2C_UNK g();')
    assert repair(src, 3, 'too many arguments to function `g\'') == out
    assert repair(src, 3, 'too few arguments to function', 1) is None


def test_a_call_through_a_pointer_type_with_the_wrong_parameters_drops_them():
    src = 'void f(void) {\n    M2C_FIELD(t, M2C_UNK (**)(void *, void *), 0x34)(a);\n}\n'
    assert repair(src, 2, 'too few arguments to function') == \
        'void f(void) {\n    M2C_FIELD(t, M2C_UNK (**)(), 0x34)(a);\n}\n'


def test_an_sn64_diagnostic_is_applied_to_the_first_line_it_fits():
    src = 'void f(void) {\n    x = 1;\n    *(s32 *)((a * 4) + &T)(b);\n}\n'
    assert repair(src, 0, 'called object is not a function') == \
        'void f(void) {\n    x = 1;\n    ((s32 (*)()) *(s32 *)((a * 4) + &T))(b);\n}\n'
    assert repair('void f(void) {}\n', 0, 'called object is not a function') is None


def test_an_sn64_line_search_skips_the_preprocessor_lines():
    src = '#define F(e, t, o) (*(t)((s8 *)(e) + (o)))(x)\nvoid f(void) {\n    *(s32 *)((a * 4) + &T)(b);\n}\n'
    assert '#define F(e, t, o) (*(t)((s8 *)(e) + (o)))(x)' in repair(src, 0, 'called object is not a function')


def test_ido_operator_classes_and_argument_counts_are_read():
    log = ("cfe: Error: func.c, line 3: Unacceptable operand of a multiplicative operator.\n x\n"
           "cfe: Error: func.c, line 4: The number of arguments doesn't agree with the number in the declaration.\n x\n"
           "cfe: Error: func.c, line 5: Unacceptable operand of relational operator.\n x\n"
           "cfe: Error: func.c, line 6: Non-function name referenced in function call.\n x\n")
    assert diagnostics(log) == [(3, 'invalid operands to binary *'), (4, 'too few arguments to function'),
                                (5, 'invalid operands to binary <'), (6, 'called object is not a function')]
    source = 'void f(u8 *a) {\n    x = a * 4;\n    y = a > b;\n}\n'
    assert repair(source, 2, 'invalid operands to binary *') == 'void f(u8 *a) {\n    x = (s32)a * (s32)4;\n    y = a > b;\n}\n'
    assert repair(source, 3, 'invalid operands to binary <') == 'void f(u8 *a) {\n    x = a * 4;\n    y = (s32)a > (s32)b;\n}\n'


def test_a_call_that_disagrees_with_its_own_definition_goes_through_an_unprototyped_pointer():
    source = 'void g(s32 a) {\n    g(a, 1);\n}\n'
    out = repair(source, 2, "too few arguments to function")
    assert out == 'void g(s32 a) {\n    ((s32 (*)())g)(a, 1);\n}\n'


def test_a_float_base_of_an_m2c_field_is_converted_through_a_word():
    source = 'void f(f32 a) {\n    x = M2C_FIELD(a, u16 *, 6);\n}\n'
    assert repair(source, 2, 'ido: float cast to a pointer') == 'void f(f32 a) {\n    x = M2C_FIELD((s32)a, u16 *, 6);\n}\n'
