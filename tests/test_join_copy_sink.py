from decomprepair import join_copy_sink_repairs

# m2c's draft of an N64 game function (GCC 2.7.2): a copy before the inner guard, the same copy at the join label.
SOURCE = '''void f(void) {
    u32 var_s2;
    s32 var_s3;
    s32 var_v0;

    var_s3 = 0;
    if (gActor != NULL) {
        var_v0 = var_s3;
        if (M2C_FIELD(gActor, void **, 0x70) != NULL) {
            for (var_s2 = 0; var_s2 < 1U; var_s2++) {
                if (g(var_s2)) {
                    var_s3 = 1;
                }
            }
            goto block_9;
        }
    } else {
block_9:
        var_v0 = var_s3;
    }
    if (var_v0 == 0) {
        h();
    }
}
'''


def test_copy_sunk_into_both_arms_of_one_merged_guard():
    (family, out), = join_copy_sink_repairs.variants(SOURCE, 'f')
    assert family == 'join_copy_sink'
    assert 'goto' not in out and 'block_9' not in out
    assert 'if (gActor != NULL && M2C_FIELD(gActor, void **, 0x70) != NULL) {' in out
    assert '        }\n        var_v0 = var_s3;\n    } else {\n        var_v0 = var_s3;\n    }\n    if (var_v0 == 0)' in out
    assert '    var_s3 = 0;\n    if (gActor' in out


def test_a_lower_precedence_condition_is_parenthesised():
    source = SOURCE.replace('if (gActor != NULL) {', 'if (a || b) {')
    (_, out), = join_copy_sink_repairs.variants(source, 'f')
    assert 'if ((a || b) && M2C_FIELD(gActor, void **, 0x70) != NULL) {' in out


def test_left_alone_when_the_copies_differ_or_the_label_has_other_jumps():
    assert join_copy_sink_repairs.variants(SOURCE.replace('block_9:\n        var_v0 = var_s3;', 'block_9:\n        var_v0 = 0;'), 'f') == []
    assert join_copy_sink_repairs.variants(SOURCE.replace('var_s3 = 1;', 'var_s3 = 1;\n                    goto block_9;'), 'f') == []
    assert join_copy_sink_repairs.variants('void g(void) {\n}\n', 'f') == []
