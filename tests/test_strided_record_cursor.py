from decomprepair.strided_record_cursor import FAMILY, LOOP, variants

SAVED = '''#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
extern s16 *gPool;

s16 *f(void *arg0, s32 arg1) {
    char *var_far;
    char *var_cur;
    s16 *var_v0;
    s32 var_i;

    var_cur = gPool;
    var_i = 0;
    var_far = var_cur + 0x20;
loop_1:
    if (M2C_FIELD(var_far, s32 *, 0x8) != arg1) {
        if (var_cur != arg0) {
            var_v0 = var_cur;
            if (M2C_FIELD(arg0, s32 *, 0x28) == *(s16 *)var_cur) {
                M2C_FIELD(var_far, s32 *, -4) += M2C_FIELD(arg0, u16 *, 0x10);
                return var_cur;
            }
            return var_v0;
        }
    }
    var_i += 1;
    var_far += 0x30;
    var_cur += 0x30;
    if (var_i >= 0x40) {
        goto block_2;
    }
    goto loop_1;
block_2:
    var_v0 = NULL;
    return var_v0;
}
'''


def child(family, source=SAVED):
    return next((text for found, text in variants(source, 'f') if found == family), None)


def test_two_cursors_become_one_record_pointer():
    text = child(FAMILY)
    assert ('typedef struct { s16 f_0; char pad_2[0xE]; u16 f_10; char pad_12[0xA]; s32 f_1C; char pad_20[0x8]; '
            's32 f_28; char pad_2C[0x4]; } __repair_stride_var_cur;') in text
    assert '__repair_stride_var_cur *var_cur;' in text and 'var_far' not in text
    assert 'var_cur = (__repair_stride_var_cur *) (gPool);' in text
    assert 'var_cur += 1;' in text
    assert 'if (var_cur->f_28 != arg1)' in text
    assert 'var_cur->f_1C += ((__repair_stride_var_cur *) arg0)->f_10;' in text
    assert '== var_cur->f_0)' in text
    assert 'return (void *) var_cur;' in text and 'var_v0 = (void *) var_cur;' in text


def test_the_goto_loop_comes_with_the_record():
    """The N64 pool search: the record alone 4814, the loop alone 4280, both 2327 -> 1730."""
    text = child(LOOP)
    assert variants(SAVED, 'f')[0][0] == LOOP
    assert 'goto' not in text.split('do {')[1].split('} while')[0]
    assert '} while (var_i < 0x40);\n    var_v0 = NULL;\n    return var_v0;\n' in text
    assert 'loop_1:' not in text


def test_left_alone():
    # a cursor used some other way, fields beyond the stride, and cursors stepped by different amounts
    assert variants(SAVED.replace('var_i += 1;', 'var_i += var_cur[1];'), 'f') == []
    assert variants(SAVED.replace('s32 *, 0x8)', 's32 *, 0x40)'), 'f') == []
    assert variants(SAVED.replace('var_far += 0x30;', 'var_far += 0x34;'), 'f') == []
