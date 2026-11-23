"""m2c's `M2C_FIELD` and `M2C_UNK` written as the C the draft's own macro block defines them to be."""
from decomprepair import m2c_spelling

BLOCK = """\
#ifndef M2C_DEFINES
#define M2C_DEFINES
typedef s32 M2C_UNK;
typedef s8 M2C_UNK8;
typedef s16 M2C_UNK16;
typedef s32 M2C_UNK32;
#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
#define M2C_BITWISE(type, expr) ((type)(expr))
#endif
"""
DRAFT = BLOCK + """
M2C_UNK func_80001000(void *arg0, s32 arg1) {
    M2C_UNK16 temp_v0;

    temp_v0 = M2C_FIELD(M2C_FIELD(arg0, void **, 0x68), s16 *, 0xE);
    M2C_FIELD(arg0, s32 *, arg1 * 4) = M2C_BITWISE(s32, temp_v0);
    return M2C_FIELD(&D_80100000, s32 *, 8);
}
"""


def test_fields_and_unknown_types_are_written_out_and_the_block_stays():
    text = m2c_spelling.plain(DRAFT)
    body = text[len(BLOCK):]
    assert text.startswith(BLOCK)
    assert 'M2C_FIELD' not in body and 'M2C_UNK' not in body
    assert 's32 func_80001000(void *arg0, s32 arg1) {' in body
    assert '    s16 temp_v0;' in body
    assert 'temp_v0 = (*(s16 *)((s8 *)(*(void **)((s8 *)arg0 + 0x68)) + 0xE));' in body
    assert '(*(s32 *)((s8 *)arg0 + (arg1 * 4))) = M2C_BITWISE(s32, temp_v0);' in body
    assert 'return (*(s32 *)((s8 *)&D_80100000 + 8));' in body
    assert m2c_spelling.variants(DRAFT, 'func_80001000') == [('m2c_spelling', text)]


def test_a_draft_whose_macro_differs_keeps_its_fields():
    other = DRAFT.replace('((s8 *)(expr) + (offset))', '((u8 *)(expr) + (offset) * 2)')
    assert 'M2C_FIELD(arg0, s32 *' in m2c_spelling.plain(other)
    assert m2c_spelling.variants(DRAFT[len(BLOCK):], 'func_80001000') == []


def test_a_longer_name_ending_in_the_macro_is_not_expanded():
    draft = DRAFT.replace('return M2C_FIELD(&D_80100000, s32 *, 8);', 'return MY_M2C_FIELD(arg0, s32 *, 8);')
    assert 'MY_M2C_FIELD(arg0, s32 *, 8)' in m2c_spelling.plain(draft)


FRAME = """\
void func_80002000(s32 *arg0) {
    struct {
        s32 sp30;
        s8 sp34;
        char reserved[20];
    } locals;
    s32 var_v0;
#define sp30 locals.sp30
#define sp34 locals.sp34
    sp30 = 1;
    sp34 = (s8) arg0[0];
    var_v0 = helper(&sp30, &sp34) + sp30;
    return;
}
"""


def test_a_frame_view_define_is_written_out_and_the_define_dropped():
    text = m2c_spelling.plain(FRAME)
    assert '#define' not in text
    assert '    locals.sp30 = 1;' in text
    assert '    locals.sp34 = (s8) arg0[0];' in text
    assert 'var_v0 = helper(&locals.sp30, &locals.sp34) + locals.sp30;' in text
    assert '    } locals;' in text and '        s32 sp30;' in text
    assert m2c_spelling.variants(FRAME, 'func_80002000') == [('m2c_spelling', text)]


def test_a_define_that_is_not_a_frame_view_stays():
    other = FRAME.replace('} locals;', '} frame;')
    assert '#define sp30 locals.sp30' in m2c_spelling.plain(other)
    outside = '#define sp30 locals.sp30\nvoid f(void) { sp30 = 1; }\n'
    assert m2c_spelling.plain(outside) == outside
    redefined = FRAME.replace('#define sp34 locals.sp34\n', '#define sp34 locals.sp34\n#undef sp34\n')
    text = m2c_spelling.plain(redefined)
    assert '#define sp34 locals.sp34' in text and 'locals.sp30 = 1;' in text
