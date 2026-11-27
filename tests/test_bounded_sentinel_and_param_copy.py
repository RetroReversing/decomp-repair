"""bounded_sentinel_while and param_copy_halfword, from a digit-string drawer (KMC gcc 2.7.2, `-O1`).

Checked on small functions of the same shape, never on game code."""
from decomprepair import bounded_sentinel_while, param_copy_halfword

SCAN = """void blank(u16 *tab) {
    s32 i;

    if ((tab[8] ^ 0x10) == 0) {
        i = 0;
        do {
            tab[i + 8] = 0;
            i++;
        } while (((tab[i + 8] ^ 0x10) == 0) & (i < 4));
    }
    done(tab);
}
"""

DRAW = """void draw(s32 *out, s32 x0, s32 y0, s32 step, u16 *d) {
    s32 i;
    s32 x;
    s32 y;

    x = x0;
    y = y0;
    for (i = 0; i < 5; i++) {
        put(out, x & 0xFFFF, y & 0xFFFF, d[i]);
        x += step;
    }
}
"""


def test_the_guarded_scan_becomes_a_bounded_while():
    ((family, text),) = bounded_sentinel_while.variants(SCAN, 'blank')
    assert family == 'bounded_sentinel_while'
    assert 'i = 0; while (((tab[i + 8] ^ 0x10) == 0) && (i < 4)) {' in text
    assert 'do {' not in text and 'if (' not in text and 'done(tab);' in text


def test_the_counter_may_be_zeroed_before_the_guard():
    source = SCAN.replace('    if (', '    i = 0;\n    if (').replace('{\n        i = 0;\n        do', '{\n        do')
    ((_, text),) = bounded_sentinel_while.variants(source, 'blank')
    assert text.count('i = 0;') == 1 and '&& (i < 4)' in text


def test_a_guard_on_another_element_is_left_alone():
    assert bounded_sentinel_while.variants(SCAN.replace('if ((tab[8]', 'if ((tab[9]'), 'blank') == []


def test_a_bound_that_may_fail_at_entry_is_left_alone():
    assert bounded_sentinel_while.variants(SCAN.replace('(i < 4)', '(i < n)'), 'blank') == []
    assert bounded_sentinel_while.variants(SCAN.replace('(i < 4)', '(i < 0)'), 'blank') == []


def test_masked_copies_and_their_step_become_halfwords():
    children = [text for _, text in param_copy_halfword.variants(DRAW, 'draw')]
    assert len(children) == 2
    assert 'void draw(s32 *out, u16 x0, u16 y0, u16 step, u16 *d)' in children[0]
    assert 'u16 x;' in children[0] and 'u16 y;' in children[0] and 's32 i;' in children[0]
    assert 'put(out, x, y, d[i]);' in children[0] and 'x += step;' in children[0]
    assert 'x = step + x;' in children[1]


def test_a_local_also_passed_whole_keeps_its_width():
    source = DRAW.replace('put(out, x & 0xFFFF, y & 0xFFFF, d[i]);', 'put(out, x & 0xFFFF, y & 0xFFFF, d[i]);\n        note(x);')
    (text, *_) = [t for _, t in param_copy_halfword.variants(source, 'draw')]
    assert 's32 x;' in text and 'u16 x0' not in text and 'u16 y;' in text
