from decomprepair.nested_record_view import FAMILY, variants

PRELUDE = '''#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
extern s32 D_80096A0C;
extern s16 D_80096B10;
'''

SAVED = PRELUDE + '''void f(s32 arg0) {
    void *temp_s4;

    {
        s32 base = D_80096A0C;
        s32 rec = M2C_FIELD((base + (D_80096B10 * 0x10)), u8 *, 0x298A) * 0x510 + 0xA8 + base;
        s32 span = (arg0 * 0xC) + 0x39A;
        temp_s4 = (void *)(rec + span);
    }
    g(temp_s4);
}
'''


def children(source=SAVED):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_rows_and_slot_read_through_views_with_the_global_base():
    """The exact child on an N64 function (KMC GCC 2.7.2 -O1 -g, 99 instructions): 130 -> 0."""
    first = children()[0]
    assert ('temp_s4 = &(((f_view2 *) D_80096A0C)->r[((f_view1 *) D_80096A0C)->r[D_80096B10].f].r[arg0]);'
            in first)
    assert ('typedef struct { u8 pad[0x2980]; struct { u8 pad[0xa]; u8 f; u8 tail[0x5]; } r[1]; } f_view1;'
            in first)
    assert ('typedef struct { u8 pad[0xa8]; struct { u8 pad[0x39a]; struct { u8 b[0xc]; } r[31]; u8 tail[0x2]; } '
            'r[1]; } f_view2;') in first
    assert 'rec' not in first and 'span' not in first and 'base' not in first


def test_the_base_local_kept_is_the_second_child():
    second = children()[1]
    assert 's32 base = D_80096A0C;' in second and '((f_view2 *) base)' in second


def test_one_statement_draft():
    source = PRELUDE + '''void f(s32 arg0) {
    s32 temp_s4;
    temp_s4 = (M2C_FIELD(D_80096A0C + (D_80096B10 * 0x10), u8 *, 0x298A) * 0x510) + 0xA8 + D_80096A0C + ((arg0 * 0xC) + 0x39A);
    g(temp_s4);
}
'''
    first = children(source)[0]
    assert 'temp_s4 = (s32) &(((f_view2 *) D_80096A0C)->r[((f_view1 *) D_80096A0C)->r[D_80096B10].f].r[arg0]);' in first


def test_left_alone():
    assert children(SAVED.replace('(void *)(rec + span)', '(void *)(rec - span)')) == []
    plain = PRELUDE + 'void f(s32 a) {\n    s32 t;\n    t = a + 4;\n    g(t);\n}\n'
    assert children(plain) == []
