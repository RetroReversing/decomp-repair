"""A do-while whose test variable is read before the loop and at its end, written as the while it stands for."""
from decomprepair.loop_entry_reload import FAMILY, variants

# A line splitter (KMC GCC 2.7.2): the loop sits under `if (buf[0] != 0)` and `p` starts at `buf`.
SAVED = '''void f(s8 *out, s32 limit) {
    s8 buf[0x208];
    s8 *p;
    s32 v;
    s32 n;
    s32 k;
    buf[0] = 0;
    p = buf;
    if (buf[0] != 0) {
        if (limit) {
            v = *p;
            n = 0;
        } else {
            v = *p;
            n = 0;
        }
        do {
            k = v;
            P(k, n);
            p += 1;
            v = *p;
            n = 0;
        } while (v != 0);
    }
    Q(out);
}
'''


def _squash(text):
    return ' '.join(text.split())


def test_the_loop_becomes_a_while_with_the_read_at_the_top():
    out = [_squash(src) for fam, src in variants(SAVED, 'f') if fam == FAMILY]
    assert len(out) == 2
    out = out[:1]
    assert 'n = 0; while (*p != 0) { v = *p; k = v; P(k, n); p += 1; n = 0; }' in out[0]
    assert 'do {' not in out[0] and 'if (limit)' not in out[0]


def test_a_loop_that_may_run_with_a_zero_first_value_is_left_alone():
    unproved = SAVED.replace('if (buf[0] != 0) {', 'if (limit > 3) {')
    assert variants(unproved, 'f') == []


def test_a_loop_with_its_own_continue_is_left_alone():
    assert variants(SAVED.replace('P(k, n);', 'if (k) { continue; }'), 'f') == []


def test_a_continue_in_a_nested_loop_does_not_count():
    nested = SAVED.replace('P(k, n);', 'for (;;) { if (k) { continue; } break; }')
    assert {fam for fam, _ in variants(nested, 'f')} == {FAMILY}


def test_a_loop_whose_entry_read_differs_is_left_alone():
    assert variants(SAVED.replace('v = *p;\n            n = 0;\n        } else', 'v = *buf;\n            n = 0;\n        } else'), 'f') == []


def test_the_constant_may_move_to_the_top_of_the_body_when_nothing_after_the_loop_reads_it():
    out = [_squash(src) for _, src in variants(SAVED, 'f')]
    assert any('while (*p != 0) { n = 0; v = *p; k = v; P(k, n); p += 1; }' in s for s in out)
    read_after = [_squash(src) for _, src in variants(SAVED.replace('Q(out);', 'Q(n);'), 'f')]
    assert not any('{ n = 0; v = *p;' in s for s in read_after)


WHILE_FORM = """void f(s8 *p, s32 n) {
    s32 v;
    s32 k;
    k = 0;
    while (*p != 0)
    {
      v = *p;
      P(v, k);
      p += 1;
      k = 0;
    }
    Q(p);
}
"""


def test_a_loop_already_a_while_gets_its_constant_at_the_top():
    out = [_squash(src) for _, src in variants(WHILE_FORM, 'f')]
    assert out == ['void f(s8 *p, s32 n) { s32 v; s32 k; while (*p != 0) { k = 0; v = *p; P(v, k); p += 1; } Q(p); }']


def test_a_while_whose_constant_is_read_after_it_is_left_alone():
    assert variants(WHILE_FORM.replace('Q(p);', 'Q(k);'), 'f') == []
