from decomprepair import loop_index_inline_repairs as repairs

SOURCE = '''void f(s32 limit) {
    s32 temp_a1;
    s32 var_s0;
    s32 var_v1;
    u8 *temp_v1;

    var_s0 = 0;
    if (count != 0) {
        var_v1 = 0 & 0xFFFF;
        do {
            temp_a1 = var_v1 * 0x68;
            temp_v1 = temp_a1 + base;
            if (M2C_FIELD(temp_v1, u8 *, 0x61) != 0) {
                M2C_FIELD(temp_a1 + base, u8 *, 0x60) = 1;
            }
            var_s0 += 1;
            var_v1 = var_s0 & 0xFFFF;
        } while ((u32) (var_s0 & 0xFFFF) < count);
    }
}
'''


def _loop(text):
    return text[text.index('do {'):text.index('} while')]


def test_the_carried_index_and_its_temporaries_are_written_where_they_are_used():
    full = [text for _, text in repairs.variants(SOURCE, 'f') if 'temp_a1 =' not in text and 'var_v1 =' not in text]
    assert full
    loop = _loop(full[0])
    assert 'M2C_FIELD(((var_s0 & 0xFFFF) * 0x68) + base, u8 *, 0x60)' in loop.replace('((((', '((') or 'temp_v1' not in loop
    assert '(var_s0 & 0xFFFF) * 0x68' in loop and 'var_s0 += 1;' in loop
    assert 'var_v1 = 0 & 0xFFFF' not in full[0] and 'var_v1 = var_s0' not in full[0]


def test_every_stage_is_proposed_because_the_original_kept_some_temporaries():
    stages = repairs.variants(SOURCE, 'f')
    assert len(stages) >= 2 and len({text for _, text in stages}) == len(stages)
    assert all(family == repairs.FAMILY for family, _ in stages)


def test_a_temporary_read_after_the_loop_stays():
    source = SOURCE.replace('    }\n}\n', '    }\n    use(temp_a1);\n}\n')
    for _, text in repairs.variants(source, 'f'):
        assert 'use(temp_a1)' in text and ('temp_a1 = ' in text)


def test_an_operand_changed_before_a_use_blocks_the_inlining():
    source = SOURCE.replace('            if (M2C_FIELD(temp_v1', '            var_v1 += 1;\n            if (M2C_FIELD(temp_v1')
    assert all('temp_a1 = var_v1 * 0x68;' in text for _, text in repairs.variants(source, 'f'))


def test_a_carried_copy_that_differs_from_its_first_value_is_not_substituted():
    source = SOURCE.replace('var_v1 = 0 & 0xFFFF;', 'var_v1 = 5;')
    assert all('var_v1' in text for _, text in repairs.variants(source, 'f'))


def test_a_function_without_a_do_loop_is_declined():
    assert repairs.variants('void f(void) {\n    g();\n}\n', 'f') == []
