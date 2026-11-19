"""m2c's spNN locals as the stack record they are, and the padding parameter before a double."""
from decomprepair import conditional_ternary_repairs as t
from decomprepair import stack_record_repairs as r

SOURCE = '''f64 f(s32 arg0, s32 arg1, s32 arg2, s32 arg3, f64 arg4, s32 arg5, f64 arg6) {
    s32 sp10;
    s32 sp14;
    s32 sp18;
    s32 sp1C;
    f64 sp20;
    f64 sp28;
    s32 var_v0;

    sp14 = arg1;
    sp18 = arg2;
    sp1C = arg3;
    sp20 = arg4;
    sp28 = arg6;
    sp10 = arg0;
    if (g(&sp10) == 0) {
        var_v0 = 0x22;
        if ((u32) (arg0 - 3) >= 2U) {
            var_v0 = 0x21;
        }
        D_80100960 = var_v0;
    }
    return sp28;
}
'''


def test_the_record_and_the_signature():
    # An N64 library's math-error wrapper: exact with both and a conditional expression after them.
    labels = [f for f, _ in r.variants(SOURCE, 'f')]
    assert labels == ['stack_argument_record', 'double_padding_parameter', 'stack_argument_record']
    both = r.variants(SOURCE, 'f')[-1][1]
    assert 'f64 f(s32 arg0, s32 arg1, s32 arg2, s32 arg3, f64 arg4, f64 arg6) {' in both
    assert '''    __repair_frame.f10 = arg0;
    __repair_frame.f14 = arg1;''' in both and 'g(&__repair_frame)' in both and 'return __repair_frame.f28;' in both
    assert 's32 sp10;' not in both


def test_a_stored_value_as_a_conditional_expression():
    both = r.variants(SOURCE, 'f')[-1][1]
    out = [text for _, text in t.variants(both, 'f')]
    assert any('D_80100960 = ((u32) (arg0 - 3) < 2U) ? 0x22 : 0x21;' in text for text in out)
    assert all('var_v0' not in text for text in out)


def test_left_alone_otherwise():
    gap = SOURCE.replace('f64 sp20;', 'f64 sp30;').replace('sp20 = arg4;', 'sp30 = arg4;')
    assert [f for f, _ in r.variants(gap, 'f')] == ['double_padding_parameter']  # not contiguous
    used = SOURCE.replace('    sp10 = arg0;', '    sp10 = arg0 + arg5;')
    assert [f for f, _ in r.variants(used, 'f')] == ['stack_argument_record']  # the parameter is used
