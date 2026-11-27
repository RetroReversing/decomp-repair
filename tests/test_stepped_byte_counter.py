from decomprepair import registry, stepped_byte_counter

DRAFT = """s32 f(u8 **in, s32 *bits, s32 *left, s32 count) {
    s32 temp_v0;
    s32 var_a3;
    s32 var_t1;

    var_a3 = count;
    var_t1 = 0;
    for (;;) {
        do { temp_v0 = var_a3 - 1; } while (0);
        do { do { var_a3 = temp_v0; } while (0); } while (0);
        if ((temp_v0 & 0xFF) != 0xFF) {
            var_t1 += step(in, bits, left);
            continue;
        }
        break;
    }
    return var_t1;
}
"""


def children(source):
    return stepped_byte_counter.variants(source, 'f')


def test_the_step_is_folded_into_the_test_on_a_byte_counter():
    text = dict(children(DRAFT))[stepped_byte_counter.FOLD]
    assert 'u8 var_a3;' in text and 'temp_v0' not in text
    assert 'if ((--var_a3) != 0xFF) {' in text


def test_both_halves_of_the_step_are_narrowed_together():
    text = dict(children(DRAFT))[stepped_byte_counter.PAIR]
    assert 'u8 var_a3;' in text and 'u8 temp_v0;' in text
    assert 'var_a3 = temp_v0;' in text and 'if ((temp_v0) != 0xFF) {' in text


def test_a_stepped_parameter_gets_a_narrow_copy():
    source = DRAFT.replace('    var_a3 = count;\n', '').replace('    s32 var_a3;\n', '').replace('var_a3', 'count')
    text = dict(children(source))[stepped_byte_counter.FOLD]
    assert 'u8 count_u8 = count;' in text and 'if ((--count_u8) != 0xFF) {' in text
    assert 's32 count)' in text


def test_a_counter_stepped_inside_the_test():
    source = """void f(void) {
    s32 n;
    n = 8;
    while (1) {
        if ((--n & 0xFFFF) == 0) break;
        g();
    }
}
"""
    text = dict(children(source))[stepped_byte_counter.TEST]
    assert 'u16 n;' in text and 'if ((--n) == 0) break;' in text


def test_a_temporary_read_elsewhere_stays():
    assert children(DRAFT.replace('step(in, bits, left)', 'step(in, bits, temp_v0)')) == []


def test_a_counter_whose_address_is_taken_stays():
    assert children(DRAFT.replace('var_t1 = 0;', 'var_t1 = 0; g(&var_a3);')) == []


def test_it_declares_itself():
    assert registry.get('stepped_byte_counter')
