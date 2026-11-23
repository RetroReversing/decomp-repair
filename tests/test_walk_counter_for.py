import re

from decomprepair.walk_counter_for import FAMILY, REPAIR, variants

SOURCE = """void walk(void *arg0, s32 mode)
{
    long off;
    u32 n;
    u32 k;
    void *cur;
    void *cur2;
    void *last;
    void *p;
    u16 *tbl;
    char big;
    s32 tmp;
    big = 0x78;
    n = 0;
    {
        tbl = D_Table;
        p = arg0;
    }
    do {
        if ((*((void * volatile *) (((char *) p) + 0x3D4))) == NULL) {
            *((void * volatile *) (((char *) p) + 0x3D4)) = make();
        }
        *((u16 *) (((char *) *((void * volatile *) (((char *) p) + 0x3D4))) + 0x1E)) = *tbl;
        tbl += 1;
        n += 1;
        p += 4;
    } while (n < 4U);
    if (mode == 5) {
        cur = arg0;
        off = 0;
        do {
            switch (off) {
                case 0:
                case 4:
                    start(*((void * volatile *) (((char *) cur) + 0x3E4)), 0xF);
                    if (off == 0) {
                        *((s16 *) (((char *) arg0) + 0x20)) = 0x50;
                    } else {
                        *((s16 *) (((char *) cur) + 0x20)) = 0xE0;
                    }
                    break;
                case 8:
                    if (cur == ((2 * 4) + arg0)) {
                        *((s16 *) (((char *) arg0) + 0x28)) = 1;
                    }
                    break;
                case 23:
                case 12:
                    start(*((void * volatile *) (((char *) cur) + 0x3E4)), 3);
                    break;
            }
            off += 4;
            cur += 4;
        } while (((u32) off) < 0x10);
    }
    k = 0;
    if (mode == 8) {
        cur2 = arg0;
        do {
            tmp = big * 2;
            put(*((void * volatile *) (((char *) cur2) + 0x3E4)), tmp - 0x57);
            last = *((void * volatile *) (((char *) cur2) + 0x3E4));
            ++k;
            cur2 += 4;
            finish(last);
        } while (k < 4U);
    }
}
"""


def _flat(text):
    return re.sub(r'\s+', ' ', text)


def _kids():
    return [_flat(text) for family, text in variants(SOURCE, 'walk') if family == FAMILY]


def _plain():
    """The child that keeps each loop's own counter (the merged one is the next)."""
    return _kids()[0]


def test_a_cursor_walk_becomes_the_counted_for_loop():
    first = _plain()
    assert 'for (; n < 4U; n++)' in first
    assert '(D_Table + n)' in first and '(arg0 + n * 4)' in first
    assert 'p += 4' not in first and 'tbl += 1' not in first and 'tbl = D_Table' not in first
    assert 'volatile' not in first


def test_a_byte_stepped_counter_becomes_the_unit_counter_with_its_labels_and_compares():
    first = _plain()
    assert 'for (; (u32) off < 4; off++)' in first
    assert 'switch (off)' in first and 'case 0: case 1:' in first and 'case 2:' in first and 'case 23' not in first
    assert 'case 3:' in first
    assert 'if (off == 0)' in first
    assert 'u32 off;' in first


def test_a_compare_with_the_address_of_an_element_is_the_counter_compare():
    assert 'if (off == 2)' in _plain()


def test_the_do_form_is_another_child_with_the_step_last():
    kids = _kids()
    do_form = [k for k in kids if 'do {' in k and 'n += 1;' in k]
    assert do_form and 'while (n < 4U)' in do_form[0] and 'off += 1;' in do_form[0]


def test_the_counters_of_the_loops_are_merged_when_each_is_set_to_zero_before_its_own_loop():
    merged = _kids()[1]
    assert 'for (; n < 4U; n++)' in merged and 'for (; (u32) n < 4; n++)' in merged and 'off = 0' not in merged
    assert 'u32 off;' not in merged and 'u32 k;' not in merged


def test_nothing_when_a_cursor_is_read_after_the_loop():
    after = SOURCE.replace('    k = 0;\n', '    use(p);\n    k = 0;\n')
    kids = [_flat(t) for f, t in variants(after, 'walk')]
    assert all('for (; n < 4U; n++)' not in k for k in kids)


def test_nothing_when_the_counter_does_not_start_at_zero():
    late = SOURCE.replace('    n = 0;\n', '    n = 1;\n')
    assert all('for (; n < 4U; n++)' not in _flat(t) for f, t in variants(late, 'walk'))


def test_it_declares_itself():
    assert REPAIR['variants'] is variants
    assert FAMILY in REPAIR['families']


def test_counters_are_merged_on_a_source_whose_loops_are_already_for_loops():
    from decomprepair.walk_counter_for import MERGE
    first = next(text for family, text in variants(SOURCE, 'walk') if family == FAMILY)
    assert 'u32 off;' in first and 'u32 k;' in first  # the first step's child keeps a counter per loop
    again = [_flat(text) for family, text in variants(first, 'walk') if family == MERGE]
    assert again and 'u32 off;' not in again[-1] and 'u32 k;' not in again[-1]


MID_STEP = """void voices(void *rec, s32 count)
{
    s32 i;
    s32 ch;
    void *p;
    p = rec;
    if (p != NULL) {
        i = 0;
        do {
            ch = i & 0xFF;
            put(7, ch, *((u8 *) (((char *) p) + 5)));
            i += 1;
            put(10, ch, *((u8 *) (((char *) p) + 6)));
            put(91, ch, *((u8 *) (((char *) p) + 7)));
            p += 8;
        } while (i < 16);
    }
}
"""


def test_a_counter_stepped_among_the_calls_and_a_companion_read_after_it_is_still_a_counted_loop():
    children = [c for f, c in variants(MID_STEP, 'voices') if f == FAMILY]
    assert children
    child = children[0]
    assert 'p += 8;' not in child and 'i += 1;' not in child
    assert '(rec + i * 8)' in child
    assert re.search(r'for \(; i < 16; i\+\+\)', child)
    assert 'p = rec;' in child  # the NULL test above the loop still reads it


def test_a_companion_read_after_its_own_step_is_left_alone():
    source = MID_STEP.replace('            p += 8;\n', '            p += 8;\n            put(92, ch, *((u8 *) (((char *) p) + 0)));\n')
    assert not [c for f, c in variants(source, 'voices') if f == FAMILY]
