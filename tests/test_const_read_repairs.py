"""Read-only pointers made const so gcc 2.7.2 may lift their loads between the prologue's saves (three N64 functions)."""
from decomprepair import const_read_repairs as c

# a typed parameter only read, like an angle triple turned into a rotation
TYPED = '''void f(f32 *in, f32 *out) {
    f32 a = in[0] * 0.5f;
    f32 b = in[1] * 0.5f;
    out[0] = g(a) * g(b);
}
'''
# m2c's fields: reads through three arguments, writes through one, one argument passed on
FIELDS = '''s32 f(void *arg0, void *arg1, void *arg2, f32 arg3) {
    f32 x;
    f32 y;

    x = M2C_FIELD(arg1, f32 *, 0);
    y = M2C_FIELD(arg2, f32 *, 4) + M2C_FIELD(arg1, f32 *, 8);
    M2C_FIELD(arg0, f32 *, 0) = x * y * arg3;
    M2C_FIELD(arg0, f32 *, 4) += y;
    h(arg2);
    return 1;
}
'''
EARLY = '''glabel f
/* 0 80000000 27BDFFB8 */  addiu      $sp, $sp, -0x48
/* 4 80000004 F7B40018 */  sdc1       $fs0, 0x18($sp)
/* 8 80000008 C4940000 */  lwc1       $fs0, 0x0($a0)
/* C 8000000C F7B60020 */  sdc1       $fs1, 0x20($sp)
/* 10 80000010 AFBF0010 */  sw         $ra, 0x10($sp)
/* 14 80000014 0C000000 */  jal        g
/* 18 80000018 00000000 */   nop
/* 1C 8000001C AFA20030 */  sw         $v0, 0x30($sp)
'''
LATE = '''glabel f
/* 0 80000000 27BDFFB8 */  addiu      $sp, $sp, -0x48
/* 4 80000004 F7B40018 */  sdc1       $fs0, 0x18($sp)
/* 8 80000008 AFBF0010 */  sw         $ra, 0x10($sp)
/* C 8000000C C4940000 */  lwc1       $fs0, 0x0($a0)
/* 10 80000010 0C000000 */  jal        g
/* 14 80000014 00000000 */   nop
/* 18 80000018 AFA20030 */  sw         $v0, 0x30($sp)
'''


def test_a_typed_parameter_only_read_becomes_const():
    texts = [t for _, t in c.variants(TYPED, 'f')]
    assert 'void f(const f32 *in, f32 *out) {' in texts[0]
    assert all(family == c.FAMILY for family, _ in c.variants(TYPED, 'f'))


def test_field_reads_become_const_and_writes_stay_plain():
    both, reads, params = [t for _, t in c.variants(FIELDS, 'f')]
    assert 'M2C_FIELD(arg1, const f32 *, 0)' in reads and 'M2C_FIELD(arg1, const f32 *, 8)' in reads
    assert 'M2C_FIELD(arg0, f32 *, 0) = ' in reads and 'M2C_FIELD(arg0, f32 *, 4) += ' in reads
    assert reads.startswith('s32 f(void *arg0, void *arg1, void *arg2')
    # arg0 is written and arg2 passed on; only arg1 is a read-only parameter
    assert 's32 f(void *arg0, const void *arg1, void *arg2, f32 arg3)' in both
    assert 's32 f(void *arg0, const void *arg1, void *arg2, f32 arg3)' in params and 'M2C_FIELD(arg1, f32 *, 0)' in params


def test_the_target_habit_is_an_argument_load_between_the_prologue_saves():
    assert c.early_load(EARLY)
    assert not c.early_load(LATE)  # (the spill after the call doesn't count)
    assert not c.early_load('')


def test_nothing_read_only_means_no_variant():
    assert c.variants('void f(s32 *p) {\n    *p = 1;\n}\n', 'f') == []
