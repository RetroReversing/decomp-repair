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


def test_a_local_flag_clear_passes_member_stores_and_a_call_that_do_not_name_it():
    # An 874-instruction object spawner (KMC GCC 2.7.2): `kind = 0;` after a call and two stores was the target's
    # above the call (15 -> 0): set there, the flag lives across the call and takes a saved register.
    source = '''void f(Rec *rec, s32 id)
{
    s32 mode;
    s8 kind;

    scan(rec, &mode);
    rec[id].loaded = 1;
    mode = 1;
    kind = 0;
    if (kind == 0) {
        g();
    }
}
'''
    children = [text for _, text in variants(source, 'f')]
    assert any(t.index('kind = 0;') < t.index('scan(rec, &mode);') for t in children)
    # a store that names the flag, or an address-taken flag, keeps it below
    named = source.replace('rec[id].loaded = 1;', 'rec[kind].loaded = 1;')
    assert all(t.index('kind = 0;') > t.index('rec[kind].loaded = 1;') for _, t in variants(named, 'f'))
    taken = source.replace('scan(rec, &mode);', 'scan(rec, &kind);')
    assert all(t.index('kind = 0;') > t.index('scan(rec, &kind);') for _, t in variants(taken, 'f'))


def test_a_float_constant_slides_and_declarations_are_not_a_run():
    # An effect spawner (KMC GCC 2.7.2): `height = 120.0f;` above three statements, away from its copy, 80 -> 70.
    from decomprepair import statement_slide as s
    source = ('void f(void *a)\n{\n  f32 height;\n  f32 y;\n  void *t;\n  s32 k;\n  s32 m;\n'
              '  t = *((void **) (((char *) a) + 0x6C));\n  k = 3;\n  m = k + 1;\n  height = 120.0f;\n  y = height;\n'
              '  g(t, k, m, y);\n}\n')
    out = [text for _, text in s.variants(source, 'f')]
    assert any(o.index('height = 120.0f;') < o.index('k = 3;') for o in out)
    assert not any(o.index('f32 y;') < o.index('f32 height;') for o in out)


# A sound-sequence interpreter's pan command (KMC GCC 2.7.2, N64): the saved best's cast spelling of the fields.
CAST_ARM = '''void f(void *arg0, s32 v)
{
  u8 t;
  *((u16 *) (((char *) arg0) + 0x50)) = v;
  t = *((u8 *) (((char *) arg0) + 0x4A));
  *((u8 *) (((char *) arg0) + 0xC0)) = (s8) (*((u16 *) (&D_800FDB9C)));
  g(t);
}
'''


def test_a_cast_spelled_field_read_slides_past_another_fields_store():
    kids = [src for _, src in variants(CAST_ARM, 'f')]
    want = CAST_ARM.replace("""  t = *((u8 *) (((char *) arg0) + 0x4A));
  *((u8 *) (((char *) arg0) + 0xC0)) = (s8) (*((u16 *) (&D_800FDB9C)));
""", """  *((u8 *) (((char *) arg0) + 0xC0)) = (s8) (*((u16 *) (&D_800FDB9C)));
  t = *((u8 *) (((char *) arg0) + 0x4A));
""")
    assert want in kids


def test_a_cast_spelled_read_of_the_stored_field_stays():
    text = CAST_ARM.replace('+ 0x4A))', '+ 0xC0))')
    kids = [src for _, src in variants(text, 'f')]
    assert not any(k.index('t = *') > k.index('+ 0xC0)) = (s8)') for k in kids)


def test_a_global_read_does_not_pass_a_store_through_a_pointer():
    text = CAST_ARM.replace('t = *((u8 *) (((char *) arg0) + 0x4A));', 't = *((u8 *) (&D_800FDB9C));')
    kids = [src for _, src in variants(text, 'f')]
    assert not any(k.index('t = *') > k.index('+ 0xC0)) = (s8)') for k in kids)
