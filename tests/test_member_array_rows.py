"""A scaled-index record access becomes an array member of a structure: gcc 2.7.2's `addu` then has the base first."""
from decomprepair import member_array_rows as m

SOURCE = '''extern s32 gBase;
extern char gOther[];

void f(s32 arg0, s32 arg1) {
    *(u16 *)(gOther + (arg0 * 0x38)) = 1;
    M2C_FIELD((gBase + (arg0 * 0x10)), s8 *, 0x298B) = arg1;
    *(u8 *)((s8 *)(gBase + (arg0 * 0x10)) + 0x298A) = 2;
}
'''


def test_a_group_becomes_one_structure_with_an_array_member():
    out = dict(m.variants(SOURCE, 'f'))
    assert set(out) == {'member_array_rows'}
    text = m.variants(SOURCE, 'f')[0][1]
    assert 'struct __rows_gBase_10 { char pad[0x2980]; struct { char p0[0xa]; u8 ma; s8 mb; char pc[0x4]; } e[1]; };' in text
    assert '(((struct __rows_gBase_10 *)gBase)->e[arg0].mb) = arg1;' in text
    assert '(((struct __rows_gBase_10 *)gBase)->e[arg0].ma) = 2;' in text
    assert '(((struct __rows_gOther_38 *)gOther)->e[arg0].m0) = 1;' in text
    assert 'M2C_FIELD' not in text.split('void f')[1]


def test_each_group_alone_is_also_offered():
    texts = [t for _, t in m.variants(SOURCE, 'f')]
    assert len(texts) == 3
    assert any('gOther_38' not in t and 'gBase_10 *)gBase' in t for t in texts)
    assert any('gBase_10 *)' not in t.split('void f')[1] and 'gOther_38 *)gOther' in t for t in texts)


def test_either_operand_order_and_shifts_are_read():
    source = 'void f(s32 i) {\n    *(s16 *)((i * 2) + D + 0x295A) = 0;\n    *(s16 *)(D + (i << 1) + 0x295A) = 1;\n}\n'
    (_, out), = m.variants(source, 'f')
    assert 'struct __rows_D_2 { char pad[0x295a]; struct { s16 m0; } e[1]; };' in out
    assert '(((struct __rows_D_2 *)D)->e[i].m0) = 0;' in out
    assert '(((struct __rows_D_2 *)D)->e[i].m0) = 1;' in out


def test_what_does_not_fit_a_row_is_left_alone():
    source = 'void f(s32 i) {\n    *(s8 *)(D + (i * 16) + 0x2980) = 0;\n    *(s32 *)(D + (i * 16) + 0x2992) = 0;\n}\n'
    (_, out), = m.variants(source, 'f')
    assert '*(s32 *)(D + (i * 16) + 0x2992) = 0;' in out  # misaligned for its width
    assert 'e[i].m0' in out


def test_no_scaled_index_no_child():
    assert m.variants('void f(s32 i) {\n    *(s8 *)(D + 3) = 0;\n    *(s8 *)(D + i) = 0;\n}\n', 'f') == []
    assert m.variants('void f(s32 i) {\n    *(s8 *)(D - (i * 16)) = 0;\n}\n', 'f') == []
