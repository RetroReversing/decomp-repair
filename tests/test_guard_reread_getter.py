from decomprepair.guard_reread_getter import FAMILY, variants

SAVED = '''#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
extern s32 gSizes[];

s32 f(void *arg0) {
    u16 temp_a0;
    s32 var_s0;

    if (M2C_FIELD(arg0, u16 *, 0x6A) != 0xFFFF) {
        temp_a0 = M2C_FIELD(arg0, u16 *, 0x6A);
        var_s0 = gSizes[temp_a0];
        if (temp_a0 != 0xFFFF) {
            return var_s0;
        }
    }
    return 0;
}
'''


def test_the_second_read_goes_through_an_inline_getter():
    [(family, text)] = variants(SAVED, 'f')
    assert family == FAMILY
    assert ('static inline int __repair_temp_a0_or_none(void *p) {\n'
            '    if (M2C_FIELD(p, u16 *, 0x6A) != 0xFFFF) {\n        return M2C_FIELD(p, u16 *, 0x6A);\n    }\n'
            '    return 0xFFFF;\n}\ns32 f(void *arg0) {') in text
    assert 'temp_a0 = __repair_temp_a0_or_none(arg0);' in text
    assert 'if (M2C_FIELD(arg0, u16 *, 0x6A) != 0xFFFF)' in text


def test_a_typed_member_read():
    source = SAVED.replace('M2C_FIELD(arg0, u16 *, 0x6A)', '((Rec *) arg0)->type')
    [(_, text)] = variants(source, 'f')
    assert 'return ((Rec *) p)->type;' in text


def test_left_alone():
    assert variants(SAVED.replace('if (temp_a0 != 0xFFFF)', 'if (var_s0 != 0)'), 'f') == []
    assert variants(SAVED.replace('u16 temp_a0;', 'f32 temp_a0;'), 'f') == []
