from decomprepair import guarded_exit_for_loop as repair
from decomprepair import split_store_chain

SOURCE = '''s32 f(void *obj)
{
    s32 i;
    s32 four;
    s32 low;
    void *base;
    void *walk;

    i = 4;
    base = gSlots;
    low = 8;
    four = 4;
    if (gCount > four) {
        walk = base;
        for (;;) {
            if (M2C_FIELD(walk, s32 *, 4) == 0) {
                reset(base);
                return M2C_FIELD(walk, s32 *, 0x44);
            }
            i += 1;
            if (M2C_FIELD(walk, s32 *, 8) < low) {
                low = M2C_FIELD(walk, s32 *, 8);
            }
            walk += 0x13C;
            base += 0x13C;
            if (i >= gCount) {
                goto block_12;
            }
            continue;
            break;
        }
    }
block_12:
    return low;
}
'''

DO_LOOP = '''void g(s32 *out, s32 n)
{
    s32 i;

    i = 0;
    if (n > 0) {
        do {
            out[i] = i;
            i += 1;
        } while (i < n);
    }
}
'''


def test_the_goto_exit_loop_is_written_as_a_for_with_its_starts():
    [(family, text)] = repair.variants(SOURCE, 'f')
    assert family == 'guarded_exit_for_loop'
    assert ('    for (i = 4, base = gSlots, walk = base; i < gCount; i += 1, walk += 0x13C, base += 0x13C) {\n'
            '        if (M2C_FIELD(walk, s32 *, 4) == 0) {\n') in text
    assert 'block_12' not in text and 'continue;' not in text and 'i = 4;\n' not in text
    assert 'base = gSlots;' not in text


def test_a_guarded_do_while_is_written_as_a_for():
    [(_, text)] = repair.variants(DO_LOOP, 'g')
    assert 'for (i = 0; i < n; i += 1) {\n        out[i] = i;\n    }' in text


def test_loops_whose_meaning_would_change_are_left_alone():
    # the counter read after its step, a `continue` that would now skip the step, a start that differs from the guard
    assert not repair.variants(DO_LOOP.replace('i += 1;\n', 'i += 1;\n            out[0] = i;\n'), 'g')
    assert not repair.variants(DO_LOOP.replace('out[i] = i;', 'if (out[i]) {\n                continue;\n            }'), 'g')
    assert not repair.variants(DO_LOOP.replace('i = 0;', 'i = 1;'), 'g')


REUSED = '''s32 h(void *voice, s32 a)
{
    s32 value;
    s32 result;

    value = a + 1;
    store(value);
    value = M2C_FIELD((a * 8), s32 *, 0x18);
    result = M2C_FIELD(voice, s32 *, 0x44);
    M2C_FIELD(voice, s32 *, 0x80) = value;
    M2C_FIELD(voice, s32 *, 4) = value;
    return result;
}
'''


def test_a_reused_locals_last_value_is_written_in_the_store_chain():
    found = [text for family, text in split_store_chain.variants(REUSED, 'h') if family == 'dead_value_store_chain']
    assert found and ('    result = M2C_FIELD(voice, s32 *, 0x44);\n'
                      '    M2C_FIELD(voice, s32 *, 4) = M2C_FIELD(voice, s32 *, 0x80) = M2C_FIELD((a * 8), s32 *, 0x18);\n') in found[0]


def test_a_value_read_again_or_made_in_a_loop_keeps_its_local():
    def dead(source):
        return [t for f, t in split_store_chain.variants(source, 'h') if f == 'dead_value_store_chain']

    assert not dead(REUSED.replace('return result;', 'return result + value;'))
    looped = REUSED.replace('    value = M2C_FIELD((a * 8)', '    while (a--) {\n    value = M2C_FIELD((a * 8)').replace(
        '    return result;', '    }\n    return result;')
    assert not dead(looped)
