from decomprepair import pointer_walk_index_repairs as r

DRAFT = '''extern void *D_A[];
void g(void *);

void f(void) {
    unsigned long var_s2;
    void **var_s0;
    void *temp_a0;

    var_s2 = 0;
    var_s0 = D_A;
    do {
        temp_a0 = *var_s0;
        if (temp_a0 != NULL) {
            g(*var_s0);
        }
        var_s2 += 1;
        var_s0 += 1;
    } while (var_s2 < 4U);
}
'''


def only(source):
    out = r.variants(source, 'f')
    assert len(out) == 1 and out[0][0] == 'pointer_walk_index'
    return out[0][1]


def test_the_walk_becomes_an_indexed_for_loop():
    text = only(DRAFT)
    assert 'for (var_s2 = 0; var_s2 < 4U; var_s2++) {' in text
    assert 'temp_a0 = D_A[var_s2];' in text and 'g(D_A[var_s2]);' in text
    assert 'var_s0 = D_A' not in text and 'do {' not in text and 'while (var_s2' not in text


def test_a_scalar_global_walked_by_address_is_widened_to_an_array():
    draft = DRAFT.replace('extern void *D_A[];', 'extern void *D_A;').replace('var_s0 = D_A;', 'var_s0 = &D_A;')
    text = only(draft)
    assert 'extern void *D_A[];' in text and 'D_A[var_s2]' in text


def test_a_scalar_global_named_elsewhere_is_left_alone():
    draft = DRAFT.replace('extern void *D_A[];', 'extern void *D_A;').replace('var_s0 = D_A;', 'var_s0 = &D_A;')
    draft = draft.replace('    } while (var_s2 < 4U);\n', '    } while (var_s2 < 4U);\n    g(D_A);\n')
    assert r.variants(draft, 'f') == []


def test_a_cursor_of_another_element_type_is_left_alone():
    assert r.variants(DRAFT.replace('void **var_s0;', 's32 *var_s0;'), 'f') == []


def test_a_cursor_used_other_than_through_a_read_is_left_alone():
    assert r.variants(DRAFT.replace('g(*var_s0);', 'g(var_s0);'), 'f') == []
    assert r.variants(DRAFT.replace('g(*var_s0);', '*var_s0 = 0;'), 'f') == []
    assert r.variants(DRAFT.replace('g(*var_s0);', 'var_s0[1] = 0;'), 'f') == []


def test_a_cursor_read_after_the_loop_is_left_alone():
    draft = DRAFT.replace('    } while (var_s2 < 4U);\n', '    } while (var_s2 < 4U);\n    g(var_s0);\n')
    assert r.variants(draft, 'f') == []


def test_a_bound_that_is_not_a_positive_constant_is_left_alone():
    assert r.variants(DRAFT.replace('var_s2 < 4U', 'var_s2 < n'), 'f') == []
    assert r.variants(DRAFT.replace('var_s2 < 4U', 'var_s2 < 0'), 'f') == []


def test_a_loop_that_leaves_early_is_left_alone():
    assert r.variants(DRAFT.replace('g(*var_s0);', 'break;'), 'f') == []


GUARDED = '''extern u32 limit;
extern void *items;
void consume(void *);

void f(void) {
    u8 __repair_frame[8];
    u32 i;
    void **cursor;

    i = 0;
    if (limit != 0) {
        cursor = &items;
        do {
            consume(*cursor);
            i++;
            cursor++;
        } while (i < (u32) limit);
    }
}
'''


def test_guarded_runtime_bound_tries_indexed_loop_with_and_without_padding():
    combined, padded = r.frame_variants(GUARDED, 'f')
    assert combined[0] == padded[0] == r.FAMILY
    assert combined[1] == padded[1].replace('    u8 __repair_frame[8];\n', '')
    assert 'extern void *items[];' in combined[1]
    assert 'for (i = 0; i < (u32) limit; i++) {\n        consume(items[i]);\n    }' in combined[1]
    assert 'if (limit' not in combined[1] and 'do {' not in combined[1]


def test_padding_that_is_read_survives_the_indexed_rewrite():
    source = GUARDED.replace('i = 0;', 'consume(__repair_frame);\n    i = 0;')
    assert not r.frame_variants(source, 'f')
    assert 'consume(__repair_frame);' in only(source)


def test_guard_must_cover_only_the_walk_with_the_same_unsigned_limit():
    for source in (
        GUARDED.replace('limit != 0', 'another != 0'),
        GUARDED.replace('extern u32 limit;', 'extern s32 limit;'),
        GUARDED.replace('extern u32 limit;', 'extern volatile u32 limit;'),
        GUARDED.replace('    }\n}', '    } else {\n        consume(0);\n    }\n}'),
        GUARDED.replace('cursor = &items;', 'consume(0);\n        cursor = &items;'),
        GUARDED.replace('limit);\n    }', 'limit);\n        consume(0);\n    }'),
    ):
        assert not r.variants(source, 'f')


BYTE_WALK = '''extern s32 D_800C4470;
extern s32 D_800C4474;

void f(void) {
    char *var_s0;
    char *var_s1;
    s32 var_s2;
    u32 temp_a0;

    if (D_80108788 != NULL) {
        var_s2 = 0;
        var_s1 = &D_800C4474;
        var_s0 = &D_800C4470;
        do {
            temp_a0 = g();
            if ((temp_a0 == *(s32 *)var_s0) && (temp_a0 == *(s32 *)var_s1)) {
                h();
            }
            var_s1 += 4;
            var_s2 += 1;
            var_s0 += 4;
        } while (var_s2 == 0);
    }
}
'''


def test_once_only_byte_cursor_walk_becomes_the_indexed_loop():
    out = [text for _, text in r.variants(BYTE_WALK, 'f') if 'for (' in text]
    assert len(out) == 1
    assert 'for (var_s2 = 0; var_s2 < 1U; var_s2++) {' in out[0]
    assert '(temp_a0 == ((s32 *)&D_800C4470)[var_s2]) && (temp_a0 == ((s32 *)&D_800C4474)[var_s2])' in out[0]
    assert 'do {' not in out[0] and 'var_s1 = &' not in out[0] and 'var_s1 += 4' not in out[0]
    assert '        }\n    }\n}\n' in out[0]


def test_byte_cursor_walk_is_left_alone_when_its_meaning_would_change():
    wrong_step = BYTE_WALK.replace('var_s1 += 4;', 'var_s1 += 8;')
    used_after = BYTE_WALK.replace('    }\n}\n', '    }\n    k(var_s0);\n}\n')
    other_read = BYTE_WALK.replace('*(s32 *)var_s0)', '*(s16 *)var_s0)')
    for source in (wrong_step, used_after, other_read, BYTE_WALK.replace('== 0);', '== 1);')):
        assert not [t for _, t in r.variants(source, 'f') if 'for (' in t]
