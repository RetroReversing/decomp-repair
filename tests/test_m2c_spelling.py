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
