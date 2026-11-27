"""stepped_array_reads: m2c's stepped cursors into a local array, read by the loop counter.

Synthetic shape of a 149-instruction N64 triangle test whose union split, these reads, one branch polarity and one local
per argument register took its saved best from 2004 to 0."""
from decomprepair import merge_disjoint_temporaries, walk_counter_for
from decomprepair import stepped_array_reads as s

SOURCE = '''s32 f(s16 *a) {
    u32 out[3];
    s32 d[3];
    s32 table[6];
    char *var_t0;
    s32 var_t1;
    s32 var_t2;
    s32 temp_a1;
    s32 temp_a2;
    char *var_a3;

    table[0] = a[0];
    var_a3 = out;
    var_t2 = 0;
    var_t1 = 4;
    var_t0 = table;
    do {
        temp_a2 = *(s32 *)var_t0;
        temp_a1 = *(table + var_t1);
        *(u32 *)var_a3 = d[0] - temp_a2 * temp_a1;
        var_t2 += 1;
        var_t0 += 8;
        var_t1 += 8;
        var_a3 += 4;
    } while (var_t2 < 3);
    return out[0];
}
'''

UNION = '''s32 g(s16 *a) {
    union {
        unsigned char bytes[8];
        struct { s32 value; } view_sp10;
        struct { unsigned char pad[4]; s32 value; } view_sp14;
    } m2c_initial_frame;
    s32 var_t1;
    s32 var_t2;
    s32 r;

    r = 0;
    m2c_initial_frame.view_sp10.value = a[0];
    m2c_initial_frame.view_sp14.value = a[1];
    var_t2 = 0;
    var_t1 = 0;
    do {
        r += *(&m2c_initial_frame.view_sp10.value + var_t1);
        var_t2 += 1;
        var_t1 += 4;
    } while (var_t2 < 2);
    return r & m2c_initial_frame.view_sp14.value;
}
'''


def test_both_cursors_become_counter_indices():
    texts = [text for _, text in s.variants(SOURCE, 'f')]
    both = texts[0]
    assert 'temp_a2 = table[var_t2 * 2];' in both
    assert 'temp_a1 = table[var_t2 * 2 + 1];' in both
    assert 'var_t0 +=' not in both and 'var_t1 +=' not in both and 'var_t0 = table;' not in both
    assert 'var_a3 += 4;' in both  # a cursor that is stored through is left alone
    assert len(texts) == 3


def test_a_cursor_used_elsewhere_or_a_late_read_declines():
    assert all('table[var_t2 * 2];' not in text for _, text in
               s.variants(SOURCE.replace('return out[0];', 'return *var_t0;'), 'f'))
    moved = SOURCE.replace('        var_t2 += 1;\n', '').replace('        temp_a2 =', '        var_t2 += 1;\n        temp_a2 =')
    assert s.variants(moved, 'f') == []


def test_the_union_is_split_and_the_reads_written_in_one_child():
    texts = [text for _, text in s.variants(UNION, 'g')]
    assert any('r += sp10[var_t2];' in text and 'return r & sp10[1];' in text for text in texts)


def test_the_two_argument_register_runs_merge_without_the_others():
    source = '''void f(s16 *p, s32 *o) {
    s32 temp_a1;
    s32 temp_a1_2;
    s32 temp_a2;
    s16 temp_a2_2;
    s32 temp_v0;
    s32 temp_v0_2;

    temp_a2 = M2C_FIELD(p, s16 *, 0);
    temp_a1 = M2C_FIELD(p, s16 *, 2);
    temp_v0 = temp_a2 - temp_a1;
    o[0] = temp_v0;
    temp_a2_2 = M2C_FIELD(p, s16 *, 4);
    temp_a1_2 = M2C_FIELD(p, s16 *, 6);
    temp_v0_2 = temp_a2_2 - temp_a1_2;
    o[1] = temp_v0_2;
}
'''
    texts = [text for _, text in merge_disjoint_temporaries.variants(source, 'f')]
    assert any('temp_a2_2' not in t and 'temp_a1_2' not in t and 'temp_v0_2 =' in t for t in texts)


def test_a_widened_short_needs_signed_reads_only():
    source = '''void f(s16 *p, s32 *o) {
    s32 temp_a2;
    s16 temp_a2_2;

    temp_a2 = M2C_FIELD(p, s16 *, 0);
    o[0] = temp_a2;
    temp_a2_2 = o[1] + 1;
    o[2] = temp_a2_2;
}
'''
    assert merge_disjoint_temporaries.variants(source, 'f') == []


def test_a_byte_cursor_into_a_word_array_keeps_its_byte_steps():
    texts = [text for _, text in walk_counter_for.variants(SOURCE, 'f')]
    assert texts and all('((char *) table + var_t2 * 8)' in text for text in texts)


def test_the_module_declares_itself():
    assert s.REPAIR['families'] == (s.FAMILY,)
