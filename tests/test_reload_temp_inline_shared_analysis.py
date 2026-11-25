"""reload_temp_inline analyses a source once per pass and reuses it for every temporary: the answers don't change."""
from decomprepair import reload_temp_inline as family

SOURCE = """void f(s32 *p) {
    s32 a;
    s32 b;
    a = p[0];
    b = a + 1;
    p[1] = b;
}
"""


def test_a_shared_analysis_gives_what_a_fresh_one_gives():
    shared = family._Function(SOURCE, "f")
    assert shared.ok
    for temp in shared.temps():
        assert family._inline_one(SOURCE, "f", temp, shared) == family._inline_one(SOURCE, "f", temp)


def test_variants_do_not_depend_on_the_order_temporaries_are_asked_in():
    fn = family._Function(SOURCE, "f")
    asked_forward = [family._inline_one(SOURCE, "f", t, fn) for t in fn.temps()]
    asked_backward = [family._inline_one(SOURCE, "f", t, fn) for t in reversed(fn.temps())]
    assert asked_forward == list(reversed(asked_backward))
