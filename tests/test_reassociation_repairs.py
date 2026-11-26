from decomprepair import propose
from decomprepair.reassociation_repairs import FAMILIES, variants


def forms(source, name='func'):
    return [text for _, text in variants(source, name)]


def test_a_pointer_chain_is_regrouped_the_way_the_audit_hand_edit_did():
    source = "u8 *func(u8 *s, u16 i) { return s + (i << 4) + 0x300; }"
    out = forms(source)
    assert "u8 *func(u8 *s, u16 i) { return s + ((i << 4) + 0x300); }" in out
    assert "u8 *func(u8 *s, u16 i) { return (s + 0x300) + (i << 4); }" in out
    assert source not in out and len(out) == len(set(out))


def test_an_unsigned_sum_and_a_bitwise_chain_take_every_grouping():
    out = forms("u32 func(u32 a, u32 b, u32 c) { return a + b + c; }")
    assert {'a + (b + c)', '(a + c) + b', '(b + c) + a', 'c + (a + b)'} <= {t.split('return ')[1].split(';')[0] for t in out}
    for op in '|&^':
        signed = forms(f"s32 func(s32 a, s32 b, s32 c) {{ return a {op} b {op} c; }}")
        assert any(f'a {op} (b {op} c)' in t for t in signed)


def test_a_signed_sum_is_regrouped_only_when_no_partial_sum_can_overflow():
    assert forms("s32 func(s32 a, s32 b, s32 c) { return a + b + c; }") == []
    assert forms("s32 func(s32 a, s32 b, s32 c) { return a * b * c; }") == []
    assert any('a + (b + 7)' in t for t in forms("s32 func(u16 a, u16 b) { return a + b + 7; }"))
    # three u16 factors can reach 65535^3, past an int; two small masked ones cannot
    assert forms("s32 func(u16 a, u16 b, u16 c) { return a * b * c; }") == []
    assert any('(b & 255) * (c & 15)' in t for t in forms("s32 func(s32 a, s32 b, s32 c) { return (a & 7) * (b & 255) * (c & 15); }"))


def test_floats_mixed_types_calls_and_unknown_names_are_never_regrouped():
    assert forms("f32 func(f32 a, f32 b, f32 c) { return a + b + c; }") == []
    assert forms("u32 func(s32 a, u32 b, u32 c) { return a + b + c; }") == []
    assert forms("u32 func(u32 a, u32 b) { return a + b + get(); }") == []
    assert forms("u32 func(u32 a, u32 b) { return a + b + MACRO; }") == []
    assert forms("volatile u32 v;\nu32 func(u32 a, u32 b) { return a + b + v; }") == []
    assert forms("u32 func(u32 a, u32 b) { return a + b; }") == []


def test_chains_in_conditions_initialisers_and_nested_expressions():
    source = """\
u32 func(u32 a, u32 b, u32 c)
{
  u32 x = a + b + c;
  if ((a | b | c) != 0) {
    return x;
  }
  return 0;
}
"""
    out = forms(source)
    assert any('u32 x = a + (b + c);' in t for t in out)
    assert any('if ((a | (b | c)) != 0)' in t for t in out)


def test_four_operands_have_pairs_a_nest_and_halves_and_a_chain_is_offered_once():
    out = forms("u32 func(u32 a, u32 b, u32 c, u32 d) { return a * b * c * d; }")
    assert any('a * (b * (c * d))' in t for t in out)
    assert any('(a * b) * (c * d)' in t for t in out)
    assert len(out) <= 10


def test_the_library_runs_it():
    report = propose.propose("u32 func(u32 a, u32 b, u32 c) { return a + b + c; }", 'func')
    found = {p.family for p in report.proposals if p.module == 'reassociation_repairs'}
    assert found == set(FAMILIES)


def test_a_value_stored_through_an_m2c_field_with_a_pointer_type_regroups():
    """The display-list word shape: the statement names `s32 **`, and the sum ends in a plain `char` array."""
    from decomprepair import reassociation_repairs
    source = '''extern u8 D_A;
extern u8 D_B;
extern char D_C[];

void f(void **arg0) {
    void *p;

    p = *arg0;
    M2C_FIELD(p, s32 **, 4) = (void *) ((D_A << 0xC) + ((D_B << 0xB) + D_C));
}
'''
    texts = [text for _, text in reassociation_repairs.variants(source, 'f')]
    assert any('(void *) ((D_B << 0xB) + ((D_A << 0xC) + D_C));' in text for text in texts)
