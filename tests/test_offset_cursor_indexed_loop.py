from decomprepair import registry
from decomprepair.offset_cursor_indexed_loop import FAMILY_DO, FAMILY_FOR, variants

SOURCE = '''extern s32 TABLE;

s32 f(void) {
    s32 acc;
    s32 off;
    s32 n;
    s32 temp;

    acc = 0;
    g(0);
    off = 0 * 4;
    n = 0;
    do {
        temp = *(s32 *)(off + &TABLE);
        acc |= temp;
        n += 1;
        off = n * 4;
    } while (n < 8);
    return acc;
}
'''

DO = '''extern s32 TABLE;

s32 f(void) {
    s32 acc;
    s32 n;
    s32 temp;

    acc = 0;
    g(0);
    n = 0;
    do {
        temp = ((s32 *)&TABLE)[n];
        acc |= temp;
        n += 1;
    } while (n < 8);
    return acc;
}
'''

FOR = '''extern s32 TABLE;

s32 f(void) {
    s32 acc;
    s32 n;
    s32 temp;

    acc = 0;
    g(0);
    for (n = 0; n < 8; n++) {
        temp = ((s32 *)&TABLE)[n];
        acc |= temp;
    }
    return acc;
}
'''


def test_the_cursor_becomes_the_counters_index_in_a_do_loop_and_a_for_loop():
    assert variants(SOURCE, 'f') == [(FAMILY_DO, DO), (FAMILY_FOR, FOR)]


def test_a_shift_step_a_byte_table_and_a_later_start_are_read():
    source = (SOURCE.replace('n * 4', 'n << 1').replace('0 * 4', '2 * 2').replace('n = 0;', 'n = 2;')
              .replace('*(s32 *)(off + &TABLE)', '*(u16 *)((u8 *)&TABLE + off)').replace('n += 1;', '++n;'))
    [(_, do), (_, loop)] = variants(source, 'f')
    assert 'temp = ((u16 *)&TABLE)[n];' in do and 'n = 2;' in do and 'off' not in do
    assert 'for (n = 2; n < 8; n++) {' in loop and '++n' not in loop


def test_the_for_loop_needs_the_counter_setup_just_before_the_loop():
    source = SOURCE.replace('off = 0 * 4;\n    n = 0;', 'n = 0;\n    off = 0 * 4;')
    assert [family for family, _ in variants(source, 'f')] == [FAMILY_DO, FAMILY_FOR]
    other = SOURCE.replace('n = 0;', 'n = 0;\n    acc = 1;')
    assert [family for family, _ in variants(other, 'f')] == [FAMILY_DO]
    assert variants(SOURCE.replace('n = 0;', 'n = 0;\n    g(1);'), 'f') == []


def test_a_cursor_used_elsewhere_or_of_the_wrong_width_is_left_alone():
    assert variants(SOURCE.replace('return acc;', 'return acc + off;'), 'f') == []
    assert variants(SOURCE.replace('off = n * 4;', 'off = n * 8;'), 'f') == []
    assert variants(SOURCE.replace('s32 *)(off', 's16 *)(off'), 'f') == []
    assert variants(SOURCE.replace('acc |= temp;', 'g(&off);'), 'f') == []
    assert variants(SOURCE.replace('acc |= temp;', 'if (temp) { continue; }'), 'f') == []
    assert variants(SOURCE.replace('off = 0 * 4;', 'off = 4;'), 'f') == []
    assert variants(SOURCE.replace('n < 8', 'n < 0'), 'f') == []


def test_a_field_macro_read_and_an_unrelated_function_name():
    source = SOURCE.replace('*(s32 *)(off + &TABLE)', 'M2C_FIELD(&TABLE, s32 *, off)')
    assert 'temp = ((s32 *)&TABLE)[n];' in variants(source, 'f')[0][1]
    assert variants(SOURCE, 'missing') == []


def test_declares_itself_with_both_families():
    repair = registry.get('offset_cursor_indexed_loop')
    assert repair and set(repair.families) == {FAMILY_DO, FAMILY_FOR}
