"""`close` and the counted-loop scan answer as the plain character scan and string slices did, without their cost."""
import random

from decomprepair import counted_loop_shapes as shapes
from decomprepair.integer_repair_support import view
from decomprepair.pattern_repairs import close


def slow_close(text, start, left='(', right=')'):
    depth = 0
    for pos in range(start, len(text)):
        depth += (text[pos] == left) - (text[pos] == right)
        if depth == 0:
            return pos + 1
    return None


def test_close_matches_the_character_scan_everywhere():
    random.seed(11)
    for _ in range(300):
        text = ''.join(random.choice('(){}[]ab; \n') for _ in range(random.randint(0, 60)))
        for start in range(len(text) + 2):
            for left, right in (('(', ')'), ('{', '}'), ('[', ']')):
                assert close(text, start, left, right) == slow_close(text, start, left, right), (text, start, left)
    assert close('f(a(b)c) d', 1) == 8 and close('{ {x} }', 0, '{', '}') == 7
    assert close('(((', 0) is None and close('x', 0) == 1 and close('', 0) is None and close('a', 5) is None


GUARDED = """void f(s32 n) {
    s32 i;
    s32 t;
    t = g(n);
    if (t != 0) {
        h(t);
    }
    i = 0;
    if (n != 0) {
        t = 1;
        do {
            k(i);
            i += 1;
        } while (i < n);
    }
    for (i = 0; i < n; i += 1) {
        k(i);
    }
    if (x) { y = 1; } else { do { z(); } while (0); }
}
"""


def test_the_scan_finds_the_same_loops_each_time_and_hands_out_its_own_objects():
    part = view(GUARDED, 'f')
    loops = shapes._loops(part)
    assert [(loop.kind, loop.counter, loop.bound) for loop in loops] == [('guarded', 'i', 'n'), ('for', 'i', 'n')]
    guarded = loops[0]
    assert guarded.part is part and guarded.pre == 't = 1;' and GUARDED[guarded.start:guarded.start + 7] == 'if (n !'
    assert part.clean[guarded.body_start:guarded.body_end].strip().startswith('k(i);')
    guarded.counter = 'changed'  # a caller's change must not reach the next caller
    again = shapes._loops(view(GUARDED, 'f'))
    assert again[0].counter == 'i' and again[0] is not guarded
    assert [loop.kind for loop in again] == ['guarded', 'for']


def test_a_block_with_no_do_loop_is_passed_over_and_a_changed_source_is_scanned_again():
    plain = GUARDED.replace('do {', 'while (1) {').replace('} while (i < n);', '}')
    assert [loop.kind for loop in shapes._loops(view(plain, 'f'))] == ['for']
    assert [loop.kind for loop in shapes._loops(view(GUARDED, 'f'))] == ['guarded', 'for']
