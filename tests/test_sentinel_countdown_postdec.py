from decomprepair import sentinel_countdown_postdec as r

LOOKUP = '''void *find(Dir *dir, s32 key) {
    s32 var_s0;
    u32 temp_s0;
    void *var_s1;

    temp_s0 = dir->count;
    var_s0 = (temp_s0 + (temp_s0 >> 0x10)) - 1;
    var_s1 = dir + 8;
    if (var_s0 != -1) {
        for (;;) {
            var_s0 -= 1;
            if (compare(key, var_s1) == 0) {
                return var_s1;
            }
            var_s1 += 0x28;
            if (var_s0 == -1) {
                goto block_5;
            }
            continue;
            break;
        }
    }
block_5:
    return NULL;
}
'''

DO_FORM = '''void clear(s32 *out, u32 n) {
    u32 i;

    i = n - 1;
    if (i != -1) {
        do {
            i -= 1;
            *out++ = 0;
        } while (i != -1);
    }
}
'''


def test_goto_exit_countdown_becomes_postdecrement_while():
    found = r.variants(LOOKUP, 'find')
    assert [family for family, _ in found] == [r.FAMILY]
    text = found[0][1]
    assert 'var_s0 = (temp_s0 + (temp_s0 >> 0x10));' in text
    assert 'while (var_s0-- != 0) {' in text
    assert 'var_s1 += 0x28;' in text and 'return NULL;' in text
    assert 'block_5' not in text and '!= -1' not in text and 'var_s0 -= 1' not in text


def test_do_while_countdown():
    text = r.variants(DO_FORM, 'clear')[0][1]
    assert 'i = n;' in text and 'while (i-- != 0) {' in text and '*out++ = 0;' in text
    assert 'do {' not in text


def test_return_exit_must_match_what_follows_the_guard():
    same = LOOKUP.replace('goto block_5;', 'return NULL;').replace('block_5:\n', '')
    assert r.variants(same, 'find')
    other = same.replace('goto block_5;', 'return NULL;').replace('                return NULL;', '                return dir;')
    assert r.variants(other, 'find') == []


def test_a_counter_the_body_reads_is_left_alone():
    reads = LOOKUP.replace('var_s1 += 0x28;', 'var_s1 += var_s0;')
    assert r.variants(reads, 'find') == []


def test_a_body_with_its_own_jump_or_a_narrow_counter_is_left_alone():
    assert r.variants(LOOKUP.replace('var_s1 += 0x28;', 'break;'), 'find') == []
    assert r.variants(LOOKUP.replace('s32 var_s0;', 's16 var_s0;'), 'find') == []


def test_a_looser_binding_start_value_is_left_alone():
    assert r.variants(DO_FORM.replace('n - 1;', 'n & n - 1;'), 'clear') == []
