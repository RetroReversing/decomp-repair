"""A guarded do-while over a bound copied from an unsigned field, as the counted for loop (a scroll window, 3427 -> 3152)."""
from decomprepair.guarded_loop_for import FAMILY, variants

HEADER = """typedef struct { char pad[9]; u8 height; } Row;
typedef struct { Row *rows; u8 selected, count; s8 delta; } Window;
"""
SOURCE = """void total_rows(Window *w)
{
    s16 i, before = 0, total = 0, old;
    s32 bound;
    s32 other;

    bound = w->selected;
    old = w->count;
    i = 0;
    if (bound) {
        do { before += w->rows[i++].height; } while (i < bound);
    }
    other = w->count;
    i = 0;
    if (other) {
        do { total += w->rows[i++].height; } while (i < other);
    }
}
"""


def children(source=SOURCE, header=HEADER):
    return [text for family, text in variants(source, 'total_rows', header) if family == FAMILY]


def test_both_loops_become_counted_for_loops_over_the_member():
    first, second = children()
    assert '    for (i = 0; i < w->selected; i++) before += w->rows[i].height;\n' in first
    assert 'bound = w->selected;' not in first
    assert '    old = w->count;\n    for (i = 0; i < w->selected' in first
    assert 'if (other) {' in first and 'i++].height' in first.split('if (other)')[1]
    assert '    for (i = 0; i < w->count; i++) total += w->rows[i].height;\n' in second
    assert 'other = w->count;' not in second


def test_a_signed_field_keeps_the_guard_because_a_negative_bound_still_runs_the_body_once():
    header = HEADER.replace('s8 delta;', 's8 delta; s16 sel;')
    source = SOURCE.replace('bound = w->selected;', 'bound = w->delta;')
    assert not [t for t in children(source, header) if 'i < w->delta' in t]


def test_a_bound_read_after_the_loop_keeps_the_copy():
    source = SOURCE.replace('    other = w->count;', '    use(bound);\n    other = w->count;')
    assert not [t for t in children(source) if 'i < w->selected' in t]
    assert [t for t in children(source) if 'i < w->count' in t]


def test_a_call_between_the_copy_and_the_loop_is_not_crossed():
    source = SOURCE.replace('    old = w->count;\n', '    old = lookup(w);\n')
    assert not [t for t in children(source) if 'w->selected; i++' in t]


def test_the_body_must_step_the_counter_once():
    source = SOURCE.replace('before += w->rows[i++].height;', 'before += w->rows[i++].height + w->rows[i++].height;')
    assert not [t for t in children(source) if 'w->selected; i++' in t]


START = """void sum_rows(Window *w)
{
    s16 i, sum;
    s32 bound;

    i = w->selected;
    bound = w->count;
    sum = 0;
    if (i < bound) {
        do { sum += w->rows[i++].height; } while (i < bound);
    }
    use(sum);
}
"""


def test_a_loop_that_starts_at_a_member_and_is_guarded_by_its_own_test_is_a_for_loop():
    [text] = [t for f, t in variants(START, 'sum_rows', HEADER) if f == FAMILY]
    assert '    sum = 0;\n    for (i = w->selected; i < w->count; i++) sum += w->rows[i].height;\n    use(sum);' in text
    assert 'bound = w->count;' not in text and 'i = w->selected;' not in text.replace('for (i = w->selected', '')


def test_a_start_that_reads_the_bound_is_left_alone():
    assert not [t for f, t in variants(START.replace('i = w->selected;', 'i = bound;'), 'sum_rows', HEADER) if 'for (i = ' in t]
