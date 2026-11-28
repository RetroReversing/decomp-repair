"""counted_search_break_for: m2c's labelled search with its cursor, written back as a `for` with a `break`."""
from decomprepair import counted_search_break_for as repair

SOURCE = '''extern s32 gReady;
void pick(s32 who) {
    char *p;
    char *q;
    u32 i;
    u32 j;
    s32 found;
    s32 seat;

    found = 0;
    seat = 0;
    i = 0;
    p = &gReady;
    (&gReady)[who] = 0;
loop_3:
    if (*(s32 *)p == 1) {
        found = 1;
        seat = i;
    } else {
        i += 1;
        p += 4;
        if (i < 3U) {
            goto loop_3;
        }
    }
    use(found, seat);
    j = 0;
    q = &gReady;
loop_9:
    if (*(s32 *)q == 2) {
        use(j, 0);
    } else {
        j += 1;
        q += 4;
        if (j < 4U) {
            goto loop_9;
        }
    }
}
'''


def test_every_search_loop_is_indexed_at_once():
    out = dict(repair.variants(SOURCE, 'pick'))
    text = out['counted_search_index_for']
    assert 'goto' not in text and 'loop_' not in text
    assert 'for (i = 0; i < 3U; i++) {' in text and 'for (j = 0; j < 4U; j++) {' in text
    assert 'if (((s32 *) &gReady)[i] == 1) {' in text and 'if (((s32 *) &gReady)[j] == 2) {' in text
    assert 'p = &gReady' not in text and 'p += 4' not in text and 'i = 0;\n    p' not in text
    assert 'seat = i;\n            break;' in text
    assert '(&gReady)[who] = 0;' in text


def test_the_cursor_form_keeps_the_pointer_and_the_zero():
    text = dict(repair.variants(SOURCE, 'pick'))['counted_search_cursor_for']
    assert 'goto' not in text
    assert '    i = 0;\n    p = &gReady;\n' in text
    assert 'for (; i < 3U; i++, p += 4) {' in text and 'if (*(s32 *)p == 1) {' in text


def test_a_cursor_used_after_the_loop_stays_a_cursor():
    source = SOURCE.replace('use(found, seat);', 'use(found, p);')
    text = dict(repair.variants(source, 'pick'))['counted_search_index_for']
    assert 'for (i = 0; i < 3U; i++, p += 4) {' in text or 'p = &gReady;' in text
    assert 'if (((s32 *) &gReady)[j] == 2) {' in text


def test_declines_a_loop_whose_first_pass_is_not_known_to_run():
    for old, new in (('i = 0;\n    p', 'i = who;\n    p'), ('i < 3U', 'i < who')):
        source = SOURCE.replace(old, new)
        for _, text in repair.variants(source, 'pick'):
            assert 'loop_3:' in text
