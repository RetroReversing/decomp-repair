from decomprepair.guard_copy_cse_barrier import FAMILY, SUFFIX, variants

SOURCE = """
void draw(void **table, s32 idx, s32 *base) {
    void *temp_v0_6;
    s32 other;
    other = base[0];
    temp_v0_6 = *(s32 *)((idx * 4) + *base);
    D_cursor += 8;
    if (temp_v0_6 != NULL) {
        if ((((Item *)temp_v0_6)->value != 0) || (prepare(temp_v0_6), (((Item *)temp_v0_6)->value != 0))) {
            emit(temp_v0_6);
        }
    }
    finish(other);
}
"""


def test_the_guarded_value_is_copied_and_the_original_reassigned():
    [(family, revised)] = variants(SOURCE, 'draw')
    assert family == FAMILY
    copy = 'temp_v0_6' + SUFFIX
    assert f'void *{copy};' in revised
    assert f'{copy} = temp_v0_6;\n        temp_v0_6 = NULL;' in revised
    assert revised.count(copy) == 6 and 'prepare(' + copy + ')' in revised
    assert 'if (temp_v0_6 != NULL) {' in revised
    assert variants(revised, 'draw') == []


def test_integers_get_a_zero_and_bare_tests_are_guards_too():
    source = SOURCE.replace('void *temp_v0_6', 'u32 temp_v0_6').replace('!= NULL', '')
    [(_, revised)] = variants(source, 'draw')
    assert 'temp_v0_6 = 0;' in revised


def test_leaves_values_read_after_the_block_or_before_the_test_alone():
    assert variants(SOURCE.replace('    finish(other);', '    finish(temp_v0_6);'), 'draw') == []
    assert variants(SOURCE.replace('    D_cursor += 8;', '    D_cursor += (s32) temp_v0_6;'), 'draw') == []
    assert variants(SOURCE.replace('prepare(temp_v0_6), ', ''), 'draw') != []
    single = SOURCE.replace('        if ((((Item *)temp_v0_6)->value != 0) || (prepare(temp_v0_6), (((Item *)temp_v0_6)->value != 0))) {\n            emit(temp_v0_6);\n        }\n', '        emit(temp_v0_6);\n')
    assert 'emit(temp_v0_6);' in single and variants(single, 'draw') == []
    assert variants(SOURCE.replace('emit(temp_v0_6);', 'emit(&temp_v0_6);'), 'draw') == []
