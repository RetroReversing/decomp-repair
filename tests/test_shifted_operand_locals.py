"""Two shifted operands of one statement, named and shifted in place before it."""
import time

from decomprepair.shifted_operand_locals import FAMILY, variants

# A fixed-point vector length (SN64 GCC 2.8.1, N64): both squares are shifted as unnamed temporaries.
LENGTH = '''s32 f(s32 x, s32 y)
{
    s32 shift = 0;
    while (x > 0x10000) {
        x >>= 1;
        shift++;
    }
    return g(((u32)(x * x) >> 12) + ((u32) (y * y) >> 0xC)) << shift;
}
'''
STATEMENT = '    return g(((u32)(x * x) >> 12) + ((u32) (y * y) >> 0xC)) << shift;\n'


def _children(text):
    return [src for fam, src in variants(text, 'f') if fam == FAMILY]


def test_both_operands_are_named_and_shifted_in_place_in_one_child():
    together, in_turn = _children(LENGTH)
    assert together == LENGTH.replace(STATEMENT, '''    {
        u32 __repair_shifted_0 = x * x;
        u32 __repair_shifted_1 = y * y;
        __repair_shifted_0 >>= 12;
        __repair_shifted_1 >>= 0xC;
        return g((__repair_shifted_0) + (__repair_shifted_1)) << shift;
    }
''')
    assert in_turn == LENGTH.replace(STATEMENT, '''    {
        u32 __repair_shifted_0 = x * x;
        u32 __repair_shifted_1;
        __repair_shifted_0 >>= 12;
        __repair_shifted_1 = y * y;
        __repair_shifted_1 >>= 0xC;
        return g((__repair_shifted_0) + (__repair_shifted_1)) << shift;
    }
''')


def test_an_operand_without_a_cast_keeps_its_signedness():
    together = _children('void f(s32 a, u32 b, s32 *out) {\n    *out = ((a * a) >> 4) + ((b + 1) >> 2);\n}\n')[0]
    assert 's32 __repair_shifted_0 = a * a;' in together
    assert 'u32 __repair_shifted_1 = b + 1;' in together


def test_globals_calls_and_single_operands_are_left_alone():
    assert not _children('void f(s32 a, s32 *out) {\n    *out = ((u32)(gx * gx) >> 4) + ((u32)(a * a) >> 4);\n}\n')
    assert not _children('void f(s32 a, s32 *out) {\n    *out = ((u32)(h(a)) >> 4) + ((u32)(a * a) >> 4);\n}\n')
    assert not _children('void f(s32 a, s32 *out) {\n    *out = (u32)(a * a) >> 4;\n}\n')


def test_a_statement_that_steps_a_name_is_left_alone():
    assert not _children('void f(s32 a, s32 *p) {\n    p[a++] = ((u32)(a * a) >> 4) + ((u32)(a + 1) >> 4);\n}\n')


def test_a_refused_expression_with_long_names_is_refused_at_once():
    src = ('void f(s32 a_very_long_integer_local_name, s32 another_long_integer_local_name) {\n'
           '    G(((a_very_long_integer_local_name * another_long_integer_local_name / 3) >> 12) + (a_very_long_integer_local_name >> 2));\n'
           '}\n')
    started = time.process_time()
    variants(src, 'f')
    assert time.process_time() - started < 5
