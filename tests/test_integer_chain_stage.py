"""A word local assigned from a chain of integer operations, written one operation per statement."""
from decomprepair.integer_chain_stage import FAMILY, variants

# A fixed-point interpolation whose result is the local the colour clamp reuses (SN64 GCC, `-O2`).
SAVED = '''static inline s32 cell(s32 *tbl, s32 row, s32 col) {
    return tbl[row * 2 + col];
}

void f(Ent *e, s32 t) {
    s32 v;

    v = (((cell(D, e->key, 1) - cell(D, e->key - 1, 1)) * t) >> 12) + cell(D, e->key - 1, 1);
    e->scale = v;
    v = (e->scale - 0x1000) >> 5;
    e->alpha = v;
}
'''


def _squash(text):
    return ' '.join(text.split())


def test_the_chain_is_written_one_operation_per_statement():
    out = [_squash(src) for fam, src in variants(SAVED, 'f') if fam == FAMILY]
    assert any('v = cell(D, e->key, 1) - cell(D, e->key - 1, 1); v *= t; v >>= 12; v += cell(D, e->key - 1, 1);' in s
               for s in out)


def test_the_s32_casts_of_a_machine_draft_are_dropped():
    src = 'void f(s32 a, s32 b, s32 t) { s32 v; v = ((s32) ((b - a) * (s32) (t << 0xC)) >> 0xC) + a; G(v); }'
    out = [_squash(s) for _, s in variants(src, 'f')]
    assert any('v = b - a; v *= t << 0xC; v >>= 0xC; v += a;' in s for s in out)


def test_the_loosest_operator_is_applied_last():
    out = [_squash(s) for _, s in variants('void f(s32 a, s32 b, s32 c) { s32 v; v = a * 3 + b * c - 1; G(v); }', 'f')]
    assert out == ['void f(s32 a, s32 b, s32 c) { s32 v; v = a * 3; v += b * c; v -= 1; G(v); }']


def test_a_single_operation_is_left_alone():
    assert variants('void f(s32 a, s32 b) { s32 v; v = a + b; G(v); }', 'f') == []


def test_unsigned_values_are_left_alone():
    assert variants('void f(u32 a, s32 b) { s32 v; v = ((a - b) >> 4) + 1; G(v); }', 'f') == []
    assert variants('void f(s32 a) { s32 v; v = ((a - 1u) >> 4) + 1; G(v); }', 'f') == []
    assert variants('void f(s32 a) { u32 v; v = ((a - 1) >> 4) + 1; G(v); }', 'f') == []


def test_a_call_or_a_reuse_of_the_local_is_left_alone():
    assert variants('void f(s32 a) { s32 v; v = (a * H(a)) - 1; G(v); }', 'f') == []
    assert variants('void f(s32 a) { s32 v; v = a * 2; v = (v / a) * 3 - v; G(v); }', 'f') == []


def test_division_comparison_and_ternary_are_left_alone():
    for expr in ('(a - b) / 3', '((a - b) * 2) < 4', '(a - b) + (a ? 1 : 2) % 3', 'a && b + 1 - 2'):
        assert variants(f'void f(s32 a, s32 b) {{ s32 v; v = {expr}; G(v); }}', 'f') == [], expr


def test_unary_operators_and_members_are_part_of_their_operand():
    out = [_squash(s) for _, s in variants('void f(E *e) { s32 v; v = (-e->a * *(s32 *) e) + ~e->b; G(v); }', 'f')]
    assert out == ['void f(E *e) { s32 v; v = (-e->a) * (*(s32 *) e); v += ~e->b; G(v); }']
