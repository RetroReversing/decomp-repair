from decomprepair import goto_loop_invariants as repairs

SOURCE = """\
void lock(void);
void unlock(void);
s32 emit(s32, s32, u8, s32);
s32 resolve(s32);
extern u8 gActive, gPlain, gAlt;
extern s32 gNext, gFlags, gOwner;

s32 walk(s32 handle, s32 word) {
    s32 index, result = -1;
    u32 high; u32 low = word;
    s32 value = word;

    if (gActive != 0) {
        lock();
        handle = resolve(handle);
        if (handle != result) {
            high = (u32)(value & 0xffff) >> 7;
            low = value & 0x7f;
        again:
            index = handle & 0xff;
            value = index * 0x1a0;
            if (*(s32 *)((char *)&gOwner + value) != handle) goto done;
            if (*(s32 *)((char *)&gFlags + value) & 2) {
                do { emit(1, (u8)index, *(&gAlt + value), high & 0xff); } while (0);
                emit(0x21, (u8)index, *(&gAlt + value), low & 0xff);
            } else {
                emit(1, (u8)index, *(&gPlain + value), high & 0xff);
                emit(0x21, (u8)index, *(&gPlain + value), low & 0xff);
            }
            handle = *(s32 *)((char *)&gNext + index * 0x1a0);
            result = 0;
            if (handle != -1) goto again;
        }
    done:
        unlock();
    }
    return result;
}
"""


def test_the_whole_set_is_the_first_child():
    family, text = repairs.variants(SOURCE, 'walk')[0]
    assert family == 'goto_loop_invariants'
    body = text[text.index('walk(s32'):]
    assert 'goto again' not in body and 'again:' not in body
    assert 'do {\n' in body and '} while (handle != -1);' in body
    assert 'u32 high' not in body and 'low = ' not in body
    assert '((u32)(word & 0xffff) >> 7)' in body and '(word & 0x7f)' in body
    assert 'value & 0xffff' not in body
    assert 's32 emit(s32, s32, u8, u8);' in text
    assert ') & 0xff)' not in body and 'high & 0xff' not in body
    assert 'do { emit' not in body
    assert '__repair_loop_stage = index * 0x1a0;' in body


def test_shorter_combinations_follow():
    texts = [text for _, text in repairs.variants(SOURCE, 'walk')]
    assert len(texts) == 4 and len(set(texts)) == 4
    assert any('u8, s32' in text and '__repair_loop_stage' not in text for text in texts)


def test_a_loop_that_rewrites_the_parameter_is_left_alone():
    source = SOURCE.replace('result = 0;', 'result = 0; word = word + 1;')
    assert repairs.variants(source, 'walk') == []


def test_no_backward_goto_no_children():
    assert repairs.variants('s32 f(s32 a) { s32 b; b = a & 1; return b; }', 'f') == []
