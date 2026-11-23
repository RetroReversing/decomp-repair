from decomprepair.statement_slide import FAMILY, commutes, variants

SOURCE = """void f(void *p) {
    s32 a;
    s32 b;
    s32 c;
    a = M2C_FIELD(p, s8 *, 0x9C) << 0x10;
    b = M2C_FIELD(p, u16 *, 0x2C);
    M2C_FIELD(p, s32 *, 0) = (s32) (M2C_FIELD(p, s32 *, 0) | 0x80800);
    c = (b << 0x10) + a / 100;
    M2C_FIELD(p, s32 *, 0x70) = c;
}
"""


def test_independent_statements_commute_and_dependent_ones_do_not():
    assert commutes('M2C_FIELD(p, s32 *, 0) = (s32) (M2C_FIELD(p, s32 *, 0) | 0x80800);', 'c = (b << 0x10) + a / 100;')
    assert not commutes('b = M2C_FIELD(p, u16 *, 0x2C);', 'M2C_FIELD(p, u16 *, 0x2C) = 3;')
    assert not commutes('a = 1;', 'b = a + 1;')
    assert not commutes('M2C_FIELD(p, s8 *, 0x9C) = 0;', 'a = M2C_FIELD(p, s8 *, 0x9C) << 0x10;')
    # different bytes of one word do not clash; a call or a pointer store is a barrier
    assert commutes('M2C_FIELD(p, s8 *, 0x9D) = 1;', 'a = M2C_FIELD(p, s8 *, 0x9C);')
    assert not commutes('g(a);', 'b = 2;')
    assert not commutes('*q = 1;', 'b = 2;')


def test_the_flag_or_slides_past_the_quotient_but_not_past_a_store_it_feeds():
    children = [text for family, text in variants(SOURCE, 'f') if family == FAMILY]
    flagged = 'M2C_FIELD(p, s32 *, 0) = (s32) (M2C_FIELD(p, s32 *, 0) | 0x80800);'
    after = [t for t in children if t.index(flagged) > t.index('c = (b << 0x10)')]
    assert after and all('M2C_FIELD(p, s32 *, 0x70) = c;' in t for t in after)
    assert all(t.index('c = (b') < t.index('M2C_FIELD(p, s32 *, 0x70) = c;') for t in children)


def test_a_load_does_not_slide_past_a_store_to_its_cell():
    source = SOURCE.replace('    c = (b << 0x10) + a / 100;', '    M2C_FIELD(p, u16 *, 0x2C) = 7;\n    c = (b << 0x10) + a / 100;')
    for _, child in variants(source, 'f'):
        assert child.index('b = M2C_FIELD(p, u16 *, 0x2C);') < child.index('M2C_FIELD(p, u16 *, 0x2C) = 7;')


def test_control_flow_ends_a_run_and_children_are_bounded():
    assert variants('void f(void) {\n    a = 1;\n    if (a) { b = 2; }\n    c = 3;\n}\n', 'f') == []
    assert len(variants(SOURCE, 'f')) <= 40


def test_a_local_update_passes_a_statement_with_a_call_that_does_not_name_it():
    # A 1133-instruction effect spawner: `phase += 0.21f;` below the statement that calls `__cosf` (3555 -> 3215): the
    # call is a barrier to the scheduler, so only the source decides which side of it the add falls on.
    source = '''void f(f32 a)
{
    f32 phase;
    f32 turn;
    f64 sum;
    s32 n;

    phase = a;
    turn = 0.5f;
    sum = g(phase);
    phase += 0.21f;
    sum = sum + ((f64) h(turn));
    n = 1;
}
'''
    children = [text for _, text in variants(source, 'f')]
    moved = [t for t in children if t.index('sum = sum + ((f64) h(turn));') < t.index('phase += 0.21f;')]
    assert moved
    # a call that names the variable, or an update of a variable the call's statement reads, stays where it is
    named = source.replace('sum = sum + ((f64) h(turn));', 'sum = sum + ((f64) h(phase));')
    assert all(t.index('phase += 0.21f;') < t.index('sum = sum + ((f64) h(phase));') for _, t in variants(named, 'f'))
    # an address-taken local is reachable by the call
    taken = source.replace('sum = g(phase);', 'sum = g(&phase);')
    assert all(t.index('phase += 0.21f;') < t.index('sum = sum + ((f64) h(turn));') for _, t in variants(taken, 'f'))
