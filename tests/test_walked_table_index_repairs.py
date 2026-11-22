from decomprepair import walked_table_index_repairs as r

DRAFT = '''s32 notify();
s32 fallback();
extern s32 T_A;
extern char T_B[];
extern char T_C[];
extern void *g_obj;

void f(void) {
    char *var_s2;
    s32 temp_s0;
    s32 var_a2;
    u32 temp_a0;
    u32 var_s1;

    var_a2 = 0;
    if (g_obj != NULL) {
        var_s1 = 0;
        var_s2 = &T_A;
        do {
            temp_a0 = *(u32 *)((char *)g_obj + 0x30);
            temp_s0 = var_s1 * 4;
            if (((temp_a0 >> 4) == *(s32 *)var_s2) && ((temp_a0 >> 0x14) == *(s32 *)(T_B + temp_s0))) {
                notify(*(u16 *)(T_C + temp_s0));
                var_a2 = 1;
            }
            var_s2 += 4;
            var_s1 += 1;
        } while (var_s1 < 2U);
    }
    temp_s0 = var_a2;
    if ((u8)temp_s0 == 0) {
        fallback();
    }
}
'''


def children(source=DRAFT):
    return [text for family, text in r.variants(source, 'f') if family == 'walked_table_index']


def test_one_child_makes_every_edit_that_applies():
    first = children()[0]
    assert '*(s32 *)(&T_A + var_s1)' in first
    assert 'T_B + (var_s1 * 4)' in first and 'T_C + (var_s1 * 4)' in first
    assert 'var_s2' not in first and 'temp_s0 = var_s1' not in first
    assert 's32 f(void) {' in first and 'temp_s0 = fallback();' in first and 'if (temp_s0 == 0)' in first
    assert first.rstrip().endswith('return temp_s0;\n}')
    assert '(u8)' not in first


def test_each_half_is_also_offered_alone():
    out = children()
    assert len(out) == 3
    assert 'var_s2' not in out[1] and 'void f(void)' in out[1] and '(u8)temp_s0' in out[1]
    assert 'var_s2' in out[2] and 's32 f(void)' in out[2] and '&T_A + var_s1' not in out[2]


def test_a_cursor_read_after_the_loop_is_left_alone():
    draft = DRAFT.replace('    temp_s0 = var_a2;', '    notify(*(s32 *)var_s2);\n    temp_s0 = var_a2;')
    assert all('&T_A + var_s1' not in text for text in children(draft))


def test_the_offset_local_read_after_the_loop_is_not_inlined():
    draft = DRAFT.replace('    temp_s0 = var_a2;', '    var_a2 = temp_s0;\n    temp_s0 = var_a2;')
    first = children(draft)[0]
    assert '&T_A + var_s1' in first and 'temp_s0 = var_s1 * 4;' in first


def test_a_step_that_is_not_the_element_size_is_left_alone():
    assert not any('&T_A + var_s1' in t for t in children(DRAFT.replace('var_s2 += 4;', 'var_s2 += 8;')))


def test_a_returning_function_or_a_void_callee_keeps_its_tail():
    assert not any('s32 f(void)' in t for t in children(DRAFT.replace('s32 fallback();', 'void fallback();')))
    assert not any('s32 f(void)' in t for t in children(DRAFT.replace(
        '    temp_s0 = var_a2;\n', '    temp_s0 = var_a2;\n    if (temp_s0 == 7) return;\n')))


def test_a_join_label_inside_the_loop_body_is_allowed():
    draft = DRAFT.replace('                var_a2 = 1;\n            }\n', '                var_a2 = 1;\n                goto join;\n            } else {\njoin:\n            }\n')
    assert '&T_A + var_s1' in children(draft)[0]
    outside = DRAFT.replace('var_a2 = 1;', 'var_a2 = 1;\n                goto out;').replace('    temp_s0 = var_a2;', 'out:\n    temp_s0 = var_a2;')
    assert not any('&T_A + var_s1' in t for t in children(outside))
