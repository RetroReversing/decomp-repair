"""A value stepped in a `for` header beside the counter, written off the counter at its uses."""
from decomprepair.for_header_companion_index import FAMILY, variants

# The loop of a HUD drawer (SN64 GCC 2.8.1, 40 -> 0 under -mfp32 by this edit).
SAVED = '''void f(s32 *o, s32 x, s32 y) {
    s32 i;
    s32 px;
    s32 w;

    w = 24;
    for (i = 0, px = x; i < 5; px += w, i++) {
        if (o[i] != 0) {
            g(h(o[i]), px, y - 8, o[i + 8]);
        } else {
            g(k(o[i]), px, y - 8, o[i + 8]);
        }
    }
    g(0, x + w * 5, y - 7, 0);
}
'''


def _squash(text):
    return ' '.join(text.split())


def test_the_companion_is_written_off_the_counter():
    out = [_squash(s) for fam, s in variants(SAVED, 'f') if fam == FAMILY]
    want = 'for (i = 0; i < 5; i++) { if (o[i] != 0) { g(h(o[i]), x + i * w, y - 8, o[i + 8]);'
    assert any(want in s and 's32 px;' not in s and 'px' not in s for s in out)
    assert any('x + w * i' in s for s in out)


def test_either_step_order_and_a_literal_stride():
    src = SAVED.replace('px += w, i++', 'i++, px += 24')
    out = [_squash(s) for _, s in variants(src, 'f')]
    assert any('for (i = 0; i < 5; i++)' in s and 'x + i * 24' in s for s in out)


def test_the_declaration_stays_when_something_else_names_it():
    src = SAVED.replace('    g(0, x + w * 5', '    px = 3;\n    g(px, x + w * 5')
    assert not variants(src, 'f')  # read after the loop
    src = SAVED.replace('    w = 24;\n', '    w = 24;\n    px = 0;\n')
    out = [s for _, s in variants(src, 'f')]
    assert out and all('s32 px;' in s for s in out)


def test_other_loops_are_left_alone():
    for old, new in (('px += w, i++', 'px += w, i += 2'),         # counter not stepped by one
                     ('i = 0, px = x', 'i = 1, px = x'),           # counter not from 0
                     ('px += w, i++', 'px += w * 2, i++'),         # stride not a name or literal
                     ('            g(h(o[i]), px', '            px++;\n            g(h(o[i]), px'),  # assigned in body
                     ('            g(h(o[i]), px', '            w = 3;\n            g(h(o[i]), px'),  # stride changes
                     ('i = 0, px = x', 'i = 0, px = q(x)')):       # a call in the start
        assert not variants(SAVED.replace(old, new), 'f'), new
    assert not variants(SAVED, 'g')


def test_the_module_declares_itself():
    from decomprepair import registry
    assert FAMILY in {fam for item in registry.declared() for fam in item.families}
