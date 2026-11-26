"""A float assigned from one binary operation, split into an assignment and a compound assignment."""
from decomprepair.compound_operand_split import FAMILY, variants

# The tail of a steer function (KMC GCC 2.7.2, 70 -> 0): the first arm already wrote `dx *= rate`.
SAVED = '''void f(void *state, f32 rate, s32 k) {
    f32 x;
    f32 dx;
    f32 ty;
    if (k) {
        x = F(state, 0x24);
        dx = x - 1.0f;
        dx *= rate;
    }
    x = F(state, 0x24);
    ty = -0.05f;
    dx = (-x) * rate;
    F(state, 0x28) = x + dx + ty;
}
'''


def _squash(text):
    return ' '.join(text.split())


def test_the_negated_product_is_split_as_the_matched_source_had_it():
    out = [src for fam, src in variants(SAVED, 'f') if fam == FAMILY]
    assert any('dx = -x; dx *= rate;' in _squash(src) and 'dx = (-x)' not in src for src in out)


def test_every_statement_split_together_is_one_child():
    src = SAVED.replace('F(state, 0x28) = x + dx + ty;', 'ty = x * rate;\n    F(state, 0x28) = x + dx + ty;')
    out = [s for _, s in variants(src, 'f')]
    together = [s for s in out if 'dx = -x;' in s and 'ty = x;' in s]
    assert together and 'dx = (-x)' not in together[0]


def test_commutative_operators_also_swap_their_operands():
    out = [_squash(s) for _, s in variants('void f(f32 a, f32 b) { f32 v; v = a + b; F(a) = v; }', 'f')]
    assert any('v = a; v += b;' in s for s in out) and any('v = b; v += a;' in s for s in out)
    out = [_squash(s) for _, s in variants('void f(f32 a, f32 b) { f32 v; v = a - b; F(a) = v; }', 'f')]
    assert any('v = a; v -= b;' in s for s in out) and not any('v = b;' in s for s in out)


def test_other_statements_are_left_alone():
    base = 'void f(f32 a, f32 b, s32 n) {\n    f32 v;\n    s32 i;\n    %s\n    G(v, i);\n}\n'
    for body in ('v = v * a;',                     # reads itself
                 'v = a * f2(b);',                 # a call
                 'i = n * 2;',                     # not a float
                 'v = a * b + 1.0f;',              # two operators
                 'v = a;',                         # one operand
                 'if (n) v = a * b;',              # unbraced
                 'v = a < b;'):
        assert not variants(base % body, 'f'), body
    assert not variants(base % 'v = a * b;', 'g')
    assert not variants('void f(void) { volatile f32 v; f32 a; v = a * a; }', 'f')


def test_the_module_declares_itself():
    from decomprepair import registry
    assert any(r.module == 'compound_operand_split' for r in registry.declared())


def test_a_field_read_through_a_pointer_is_split_and_comes_first():
    source = ('void f(Obj *o, f32 k) { f32 a; f32 b; f32 v; a = b * k; '
              'v = ((Obj *) o)->speed / k; o->x = v + a; }')
    found = [text for family, text in variants(source, 'f') if family == FAMILY]
    assert 'v = ((Obj *) o)->speed;\n' in found[0] and 'v /= k;' in found[0]
    assert not variants('void f(Obj *o, f32 k) { f32 v; v = o->a > k; }', 'f')


def test_a_product_quotient_chain_is_split_at_its_last_operator():
    """A 378-instruction N64 colour interpolator (SN64 GCC 2.8.1 -mfp32): `w = t * s; w /= len;` 3446 -> 3235."""
    out = [_squash(s) for _, s in variants('void f(f32 t, f32 s, f32 len) { f32 w; w = t * s / len; G(w); }', 'f')]
    assert any('w = t * s; w /= len;' in s for s in out)
    assert not variants('void f(f32 t, f32 s, f32 len) { f32 w; w = t * s + len / t; G(w); }', 'f')


def test_the_combined_child_is_applied_by_place_not_by_rank():
    """The combined child used the ranked order (loads first) and garbled the text when a load came later."""
    source = 'void f(f32 a, f32 *p, f32 n) { f32 v; f32 w; v = a * n; w = p[0] / n; G(v, w); }'
    out = [_squash(s) for _, s in variants(source, 'f')]
    assert any('v = a; v *= n; w = p[0]; w /= n;' in s for s in out)


def test_an_integer_mask_is_split_with_its_first_load_first():
    """A 92-instruction N64 bit-count routine (KMC GCC 2.7.2 -O1): 205 -> 0 on this one statement."""
    source = ('extern u32 D[][8]; void f(u8 a) { u32 bits; u8 j; u32 row; '
              'for (j = 0; j < 8; j++) { bits = D[row][j] & ~D[a][j]; G(bits); } }')
    out = [_squash(s) for _, s in variants(source, 'f')]
    assert any('bits = D[row][j]; bits &= (~D[a][j]);' in s for s in out)


def test_integers_split_only_bitwise_operators():
    base = 'void f(u32 a, u32 b, u32 *p) { u32 v; %s G(v); }'
    for body in ('v = a + b;', 'v = a & b | a;', 'v = a && b;', 'v = a & v;', 'v = (u32 *) &a;', 'v = a == b;'):
        assert not variants(base % body, 'f'), body
    out = [_squash(s) for _, s in variants(base % 'v = (a << 2) | p[0];', 'f')]
    assert any('v = (a << 2); v |= (p[0]);' in s for s in out)
