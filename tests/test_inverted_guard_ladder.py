from decomprepair import arm_pointer_update_inline, inverted_guard_ladder

LADDER = """void score(int arg0) {
    s32 *var_v1;
    s32 var_v0;
    s32 mode;

    mode = level();
    if (mode != 0) {
        if (mode != 1) {
            if (mode == 2) {
                var_v1 = (arg0 * 4) + table;
                var_v0 = *var_v1 + 0x3E80;
                goto block_12;
            }
        } else {
            var_v1 = (arg0 * 4) + table;
            var_v0 = *var_v1 + 0x2EE0;
            goto block_12;
        }
    } else {
        var_v1 = (arg0 * 4) + table;
        var_v0 = *var_v1 + 0x1F40;
block_12:
        *var_v1 = var_v0;
    }
}
"""


def test_ladder_is_turned_at_every_level_and_the_arms_written_on_the_place():
    first = inverted_guard_ladder.variants(LADDER, 'score')[0][1]
    assert 'goto' not in first
    assert first.index('mode == 0') < first.index('mode == 1') < first.index('mode == 2')
    assert '!=' not in first
    for amount in ('0x1F40', '0x2EE0', '0x3E80'):
        assert f'*(s32 *)((arg0 * 4) + table) += {amount};' in first
    assert 'var_v1' not in first and 'var_v0' not in first


def test_ladder_also_offers_the_flat_chain_with_its_locals():
    texts = [text for _, text in inverted_guard_ladder.variants(LADDER, 'score')]
    assert any('goto' not in text and 'var_v1 = (arg0 * 4) + table;' in text for text in texts)


def test_a_chain_already_in_order_is_left_alone():
    source = "void f(int x) {\n    if (x == 0) {\n        a();\n    } else if (x == 1) {\n        b();\n    }\n}\n"
    assert inverted_guard_ladder.variants(source, 'f') == []


def test_a_level_with_more_than_the_next_test_is_not_turned():
    source = ("void f(int x) {\n    if (x != 0) {\n        a();\n        if (x == 1) {\n            b();\n        }\n"
              "    } else {\n        c();\n    }\n}\n")
    assert inverted_guard_ladder.variants(source, 'f') == []


def test_pointer_updates_in_each_form_are_written_on_the_place():
    source = ("void f(int i) {\n    s16 *p;\n    s32 *q;\n\n    p = i + base;\n    *p += 1;\n"
              "    q = &words[i];\n    *q = *q - 4;\n}\n")
    out = arm_pointer_update_inline.variants(source, 'f')[0][1]
    assert '*(s16 *)(i + base) += 1;' in out
    assert '*(s32 *)(&words[i]) -= 4;' in out
    assert ' *p' not in out and ' *q' not in out


def test_a_pointer_or_value_used_again_stays():
    pointer = "void f(int i) {\n    s32 *p;\n\n    p = i + base;\n    *p += 1;\n    g(p);\n}\n"
    value = ("void f(int i) {\n    s32 *p;\n    s32 v;\n\n    p = i + base;\n    v = *p + 1;\n    *p = v;\n"
             "    g(v);\n}\n")
    narrow = ("void f(int i) {\n    s32 *p;\n    s16 v;\n\n    p = i + base;\n    v = *p + 1;\n    *p = v;\n}\n")
    for source in (pointer, value, narrow):
        assert arm_pointer_update_inline.variants(source, 'f') == []


def test_a_pointer_set_by_a_side_effect_or_a_guard_stays():
    stepped = "void f(void) {\n    s32 *p;\n\n    p = cursor++;\n    *p += 1;\n}\n"
    guarded = "void f(int c) {\n    s32 *p;\n\n    if (c) p = a;\n    *p += 1;\n}\n"
    for source in (stepped, guarded):
        assert arm_pointer_update_inline.variants(source, 'f') == []
