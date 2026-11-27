"""A halfword read from inside a stack word the C stored whole, written as the word narrowed."""
from decomprepair import stack_word_half_read as r

# The shape of an N64 routine that stores three words and copies their low halves to a record (synthetic names).
SOURCE = '''void f(void *arg0, s32 a, s32 b, s32 c) {
    s32 unksp12;
    s32 unksp16;
    s32 unksp1A;
    s32 sp10;
    s32 sp14;
    s32 sp18;
    s16 sp20;

    sp10 = a * 8;
    sp14 = b * 8;
    sp18 = c * 8;
    M2C_FIELD(arg0, u16 *, 0x30) = unksp12;
    M2C_FIELD(arg0, u16 *, 0x32) = unksp16;
    M2C_FIELD(arg0, u16 *, 0x34) = unksp1A;
    sp20 = 0;
}
'''


def test_words_become_one_array_and_reads_the_low_half():
    (family, out), (view, viewed) = r.variants(SOURCE, 'f')
    assert family == 'stack_word_half_read' and view == 'stack_word_half_view'
    assert '    s32 sp10[3];\n' in out and 'unksp' not in out and 's32 sp14;' not in out
    assert 'sp10[0] = a * 8;' in out and 'sp10[2] = c * 8;' in out
    assert '= (u16) sp10[0];' in out and '= (u16) sp10[1];' in out and '= (u16) sp10[2];' in out
    assert '= ((u16 *) sp10)[1];' in viewed and '= ((u16 *) sp10)[5];' in viewed


def test_an_existing_array_only_gets_its_reads_rewritten():
    src = SOURCE.replace('s32 sp10;\n    s32 sp14;\n    s32 sp18;', 's32 sp10[3];')
    src = src.replace('sp10 =', 'sp10[0] =').replace('sp14 =', 'sp10[1] =').replace('sp18 =', 'sp10[2] =')
    (_, out), _ = r.variants(src, 'f')
    assert '(u16) sp10[2]' in out and 's32 sp10[3];' in out


def test_high_half_and_byte_reads():
    src = SOURCE.replace('unksp12', 'unksp10').replace('unksp16', 'unksp15').replace('s32 unksp15', 's8 unksp15')
    [(_, out)] = r.variants(src, 'f')
    assert '= (u16) (sp10[0] >> 16);' in out and '= (s8) (sp10[1] >> 16);' in out


def test_left_alone_when_the_slot_is_assigned_or_not_a_stored_word():
    (_, out), _ = r.variants(SOURCE.replace('    sp20 = 0;', '    unksp12 = 1;'), 'f')
    assert 'unksp12 = 1;' in out and 's32 unksp12;' in out and '(u16) sp10[0]' not in out
    assert r.variants(SOURCE.replace('sp10 = a * 8;', 'sp20 = a;').replace('sp14 = b * 8;', '').replace('sp18 = c * 8;', ''), 'f') == []
    assert r.variants(SOURCE.replace('M2C_FIELD(arg0, u16 *, 0x30)', 'x'), 'f') == []


def test_a_word_a_callee_fills_counts_as_stored():
    src = '''void f(void *arg0) {
    s32 unksp2;
    s32 unksp6;
    s32 sp0;
    s32 sp4;

    g(&sp0);
    M2C_FIELD(arg0, u16 *, 0x10) = unksp2;
    M2C_FIELD(arg0, u16 *, 0x12) = unksp6;
}
'''
    _, (_, viewed) = r.variants(src, 'f')
    assert 's32 sp0[2];' in viewed and 'g(&sp0[0]);' in viewed
    assert '= ((u16 *) sp0)[1];' in viewed and '= ((u16 *) sp0)[3];' in viewed


def test_declared_in_the_registry():
    from decomprepair import registry
    names = {f for m in registry.declared() for f in getattr(m, 'families', ())}
    assert {'stack_word_half_read', 'stack_word_half_view'} <= names
