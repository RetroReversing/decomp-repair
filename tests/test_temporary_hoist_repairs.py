from decomprepair import propose
from decomprepair.temporary_hoist_repairs import FAMILIES, variants

AUDIT = """\
u32 D;
u32 func(u32 x)
{
  return (x + (D + 0xFFFC)) & 0xFFFF;
}
"""


def texts(source, family=None, name='func'):
    return [text for label, text in variants(source, name) if family in (None, label)]


def test_holds_a_subexpression_the_audit_hand_edit_did():
    # a pre-decremented value held in a temporary and used once, in the place of the parenthesised sum
    assert """\
u32 D;
u32 func(u32 x)
{
  u32 temp;
  temp = D + 0xFFFC;
  return (x + temp) & 0xFFFF;
}
""" in texts(AUDIT, 'temporary_hoist')


def test_every_candidate_is_offered_once_with_the_expressions_own_type():
    out = texts(AUDIT)
    for held in ('temp = x + (D + 0xFFFC);', 'temp = (x + (D + 0xFFFC)) & 0xFFFF;', 'temp = D + 0xFFFC;'):
        assert any(held in text for text in out)
    assert len(out) == len(set(out))
    # `D + 0xFFFC` is u32 + int, an unsigned int; an int operand gives an int temporary
    assert 'int temp;' in texts('s32 func(u16 a, u16 b) { return (a << 2) + b; }', name='func')[0]


def test_a_repeated_expression_is_held_everywhere_or_only_in_its_first_use():
    source = """\
void func(s32 *out, s32 a, s32 b)
{
  out[0] = (a + b) * 3 + (a + b);
}
"""
    out = texts(source, 'temporary_hoist')
    assert any('temp = a + b;' in t and 'out[0] = temp * 3 + temp;' in t for t in out)
    assert any('temp = a + b;' in t and 'out[0] = temp * 3 + (a + b);' in t for t in out)


def test_a_run_continues_into_the_next_statements_until_an_operand_changes():
    source = """\
void func(s32 *out, s32 a, s32 b)
{
  out[0] = (a + b) * 2;
  out[1] = (a + b) * 3;
  a = 0;
  out[2] = (a + b) * 4;
}
"""
    run = [t for t in texts(source, 'temporary_hoist') if 'out[1] = temp * 3;' in t]
    assert run and all('out[2] = (a + b) * 4;' in t for t in run)
    assert any('out[0] = temp * 2;' in t for t in run)
    # a store through a pointer ends a run for an expression that reads memory
    loads = """\
void func(s32 *p, s32 *out)
{
  out[0] = (p[1] + 1) * 2;
  p[1] = 9;
  out[1] = (p[1] + 1) * 3;
}
"""
    assert not any('out[0] = temp * 2;' in t and 'out[1] = temp * 3;' in t for t in texts(loads, 'temporary_hoist'))
    assert any('out[0] = temp * 2;' in t for t in texts(loads, 'temporary_hoist'))


def test_the_block_variant_declares_the_temporary_at_the_head_of_the_block():
    source = """\
void func(s32 *out, s32 a, s32 b, s32 c)
{
  s32 i;
  if (c) {
    s32 j;
    out[0] = (a + b) * c;
  }
}
"""
    block = texts(source, 'temporary_hoist_block')
    assert any('    s32 j;\n    s32 temp;\n    temp = a + b;\n    out[0] = temp * c;' in t for t in block)
    top = texts(source, 'temporary_hoist')
    assert any('  s32 i;\n  s32 temp;\n  if (c) {' in t for t in top)
    # at the function's own level the two placements are one
    assert texts('void func(s32 *o, s32 a, s32 b) { o[0] = (a + b) * 3; }', 'temporary_hoist_block') == []


def test_pairs_of_a_chain_are_held_only_when_the_regrouping_is_exact():
    pointer = "u8 *func(u8 *s, u16 i) { return s + (i << 4) + 0x300; }"
    assert any('temp = (i << 4) + 0x300;' in t and 'return s + temp;' in t
               for t in texts(pointer, 'temporary_hoist_pair'))
    assert any('temp = s + 0x300;' in t and 'return temp + (i << 4);' in t for t in texts(pointer, 'temporary_hoist_pair'))
    signed = "s32 func(s32 a, s32 b, s32 c) { return a + b + c; }"
    assert texts(signed, 'temporary_hoist_pair') == []
    unsigned = "u32 func(u32 a, u32 b, u32 c) { return a + b + c; }"
    assert any('temp = a + c;' in t for t in texts(unsigned, 'temporary_hoist_pair'))


def test_nothing_is_held_where_evaluating_it_early_changes_the_program():
    # a call in the statement: a global it could change, or an address-taken local, is not held
    call = "extern s32 g;\nvoid func(s32 a) { use(g + 1, a); }"
    assert not any('temp = g + 1' in t for t in texts(call))
    plain = "void func(s32 a, s32 b) { use(a + 1, b); }"
    assert any('temp = a + 1;' in t for t in texts(plain))
    taken = "void func(s32 a) { s32 b; use(&b, b + 1); b = a; }"
    assert not any('temp = b + 1' in t for t in texts(taken))
    # the right of && / || and the arms of ?: are evaluated only sometimes
    guarded = "s32 func(s32 *p, s32 a) { if (p && p[0] + a > 1) { return 1; } return a ? p[1] + a : a; }"
    assert not any('temp = p[0] + a' in t or 'temp = p[1] + a' in t for t in texts(guarded))
    # side effects and volatile names stay where they are
    assert texts("void func(s32 a, s32 *o) { o[a++] = a + 1; }") == []
    volatile = "volatile s32 v;\nvoid func(s32 *o) { o[0] = (v + 1) * 2; }"
    assert not any('v + 1;' in t.split('o[0]')[0] for t in texts(volatile))
    # a store to the held name after the statement doesn't matter, but the statement's own store isn't held
    assert not any('temp = o[0];' in t for t in texts("void func(s32 *o, s32 a) { o[0] = a + 1; }"))


def test_unknown_types_and_unbraced_bodies_are_skipped():
    assert texts("s32 func(void) { return MACRO(1) + OTHER; }") == []
    assert texts("void func(s32 *o, s32 a, s32 b) { if (a) o[0] = a + b * 2; }") == [] or all(
        'temp = a + b' not in t for t in texts("void func(s32 *o, s32 a, s32 b) { if (a) o[0] = a + b * 2; }"))
    assert not any('else' in t.split('temp =')[0].splitlines()[-1] for t in texts(
        "void func(s32 *o, s32 a, s32 b) { if (a) { o[0] = 1; } else o[1] = a + b; }") if 'temp =' in t)


def test_the_library_runs_it_and_names_the_families():
    report = propose.propose(AUDIT, 'func')
    found = {p.family for p in report.proposals if p.module == 'temporary_hoist_repairs'}
    assert found and found <= set(FAMILIES)
    assert 'temporary_hoist_repairs' in propose.modules()


def test_a_file_with_preprocessor_lines_still_types_its_globals():
    # m2c's header of #defines ahead of `extern s32 D;` must not hide the declaration (a real audit function: 10 -> 0)
    source = """\
#ifndef M2C_DEFINES
#define M2C_DEFINES
#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
#endif

extern s32 D_801002B8;

s32 func(s32 arg0) {
    s32 temp_v1;

    temp_v1 = arg0 & 0xFFFF;
    if (temp_v1 < D_801002B8) {
        return temp_v1;
    }
    return (arg0 + (D_801002B8 + 0xFFFC)) & 0xFFFF;
}
"""
    assert any('    s32 temp;\n' in t and '    temp = D_801002B8 + 0xFFFC;\n    return (arg0 + temp) & 0xFFFF;' in t
               for t in texts(source, 'temporary_hoist'))


def test_a_load_from_a_constant_address_and_a_repeated_float_literal_are_held():
    source = """\
f32 func(f32 a)
{
  f32 out[2];
  out[0] = a - *(f32 *) 0x218680;
  out[1] = *(f32 *) 0x218680 + a;
  return out[0] + out[1];
}
"""
    out = texts(source, 'temporary_hoist')
    assert any('temp = *(f32 *) 0x218680;' in t and 'out[0] = a - temp;' in t and 'out[1] = temp + a;' in t for t in out)
    # through a pointer the store may change what the constant address holds: no run
    through = source.replace('f32 func(f32 a)', 'f32 func(f32 a, f32 *out)').replace('  f32 out[2];\n', '')
    assert not any('out[0] = a - temp;' in t and 'out[1] = temp + a;' in t for t in texts(through, 'temporary_hoist'))
    zeros = """\
void func(f32 *sp10)
{
  sp10[2] = 0.0f;
  sp10[1] = 0.0f;
  sp10[0] = 0.0f;
}
"""
    out = texts(zeros, 'temporary_hoist')
    assert any('temp = 0.0f;' in t and t.count('= temp;') == 3 for t in out)
    # a literal that is used once is not worth a name
    assert texts("void func(f32 *p) { p[0] = 0.0f; }") == []
