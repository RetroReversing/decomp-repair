"""Statement macros that hide a one-shot loop: unwrapped everywhere at once, then re-wrapped on a few uses."""
from decomprepair import macro_scope_weight as weight

SOURCE = '''#define FLIP(p) do { *(p) = -*(p); } while (0)
#define FLIP_OUT(p, q) do { FLIP(p); *(q) = 1; return 1; } while (0)
s32 f(f32 *a, s32 *b, s32 c) {
    if (c == 1) {
        FLIP_OUT(a, b);
    }
    if (c == 2) {
        FLIP_OUT(a, b);
    }
    if (c == 3) {
        FLIP_OUT(a, b);
    }
    return 0;
}
'''


def _by(family, source=SOURCE):
    return [text for name, text in weight.variants(source, 'f') if name == family]


def test_every_wrapped_macro_is_unwrapped_alone_and_together():
    out = _by('macro_one_shot_unwrap')
    assert any('#define FLIP(p) { *(p) = -*(p); }' in t and 'FLIP_OUT(p, q) do {' in t for t in out)
    assert any('#define FLIP(p) do' in t and '#define FLIP_OUT(p, q) { FLIP(p); *(q) = 1; return 1; }' in t for t in out)
    together = [t for t in out if 'while (0)' not in t]
    assert len(together) == 1 and 'FLIP_OUT(a, b);' in together[0]


def test_unwrapped_macros_offer_one_or_two_rewrapped_uses():
    base = _by('macro_one_shot_unwrap')[-1]
    out = _by('macro_one_shot_rewrap', base)
    assert len(out) == 3 + 3
    singles = [t for t in out if t.count('do { FLIP_OUT') == 1]
    pairs = [t for t in out if t.count('do { FLIP_OUT') == 2]
    assert len(singles) == 3 and len(pairs) == 3
    assert all(t.count('#define') == 2 and '#define FLIP_OUT(p, q) { FLIP(p);' in t for t in out)


def test_a_wrapped_macro_is_not_rewrapped():
    assert not _by('macro_one_shot_rewrap')


def test_function_body_wrappers_are_unwrapped_together():
    source = 'void g(s32 *a) {\n  do { *a = 1; } while (0);\n  do { *a = 2; } while (0);\n}\n'
    out = [x for n, x in weight.variants(source, 'g') if n == 'macro_one_shot_unwrap']
    assert out and out[-1] == 'void g(s32 *a) {\n  { *a = 1; }\n  { *a = 2; }\n}\n'


def test_a_use_that_is_not_a_whole_statement_keeps_the_macro_wrapped():
    # `if (c) FLIP(a); else ...` would break once the macro is a bare block
    source = SOURCE.replace('    return 0;', '    if (c == 4) FLIP(a); else c = 0;\n    return 0;')
    assert not any('#define FLIP(p) {' in t for t in _by('macro_one_shot_unwrap', source))


def test_control_flow_inside_a_macro_keeps_it_wrapped():
    source = '#define SKIP() do { if (x) break; } while (0)\nvoid g(void) {\n  SKIP();\n}\n'
    assert not weight.variants(source, 'g')
