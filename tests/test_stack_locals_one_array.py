"""Separate m2c stack locals that a call receives as one block, declared as one word array."""
from decomprepair import stack_locals_one_array as r

# The shape of an N64 argument-block builder (synthetic: its own names and constants).
SOURCE = '''void f(s32 arg0, s32 arg1) {
    s32 sp10[2];
    M2C_UNK *sp18;
    s32 sp1C[6];

    sp10[0] = 0;
    sp10[1] = 0x18;
    sp18 = &D_80001000;
    sp1C[1] = 0xC;
    sp1C[2] = arg0;
    sp1C[4] = arg1;
    sp1C[3] = 0;
    sp1C[5] = 0x40;
    g(sp10);
}
'''


def test_the_block_becomes_one_array_by_offset_and_compact():
    found = dict(((i, t) for i, (_, t) in enumerate(r.variants(SOURCE, 'f'))))
    assert len(found) == 2
    by_offset, compact = found[0], found[1]
    assert '    s32 sp10[9];\n' in by_offset and 'sp18;' not in by_offset and 'sp1C[6]' not in by_offset
    assert 'sp10[2] = (s32) (&D_80001000);' in by_offset
    assert 'sp10[4] = 0xC;' in by_offset and 'sp10[8] = 0x40;' in by_offset
    assert 'g(sp10);' in by_offset
    # the compact layout drops sp1C[0], which the C never names: the object is the game's 8 words
    assert '    s32 sp10[8];\n' in compact
    assert 'sp10[3] = 0xC;' in compact and 'sp10[4] = arg0;' in compact and 'sp10[7] = 0x40;' in compact
    assert [x for x in compact.split('\n') if 'sp10[' in x][0].strip() == 's32 sp10[8];'


def test_pointer_reads_are_cast_back():
    text = SOURCE.replace('g(sp10);', 'g(sp10, sp18);')
    (_, out), *_ = r.variants(text, 'f')
    assert 'g(sp10, ((M2C_UNK *) sp10[2]));' in out


def test_left_alone_when_nothing_escapes_or_a_member_is_a_float():
    assert r.variants(SOURCE.replace('g(sp10);', 'g(0);'), 'f') == []
    assert r.variants(SOURCE.replace('s32 sp1C[6];', 'f32 sp1C[6];').replace('M2C_UNK *sp18;', 'f32 sp18;'), 'f') == []
    # a pointer local whose address is taken is not a word of the block
    assert r.variants(SOURCE.replace('g(sp10);', 'g(&sp18);'), 'f') == []
    # a pointer updated in place is not rewritten
    assert r.variants(SOURCE.replace('g(sp10);', 'sp18 += 4;\n    g(sp10);'), 'f') == []


def test_a_dynamic_index_keeps_only_the_offset_layout():
    text = SOURCE.replace('g(sp10);', 'sp1C[arg0] = 1;\n    g(sp10);')
    found = r.variants(text, 'f')
    assert len(found) == 1 and 'sp10[9]' in found[0][1]


HOLE = '''void h(s32 arg0, void *arg1, s32 arg2) {
    u16 sp10[3];
    char frame_pad[8];
    s32 sp18;
    s32 sp2C[3];

    sp10[0] = *(u16 *)arg1;
    g(sp10, &sp18);
    sp2C[0] = ((s16 *)arg1)[4];
    sp2C[1] = ((s16 *)arg1)[5];
    sp2C[2] = ((s16 *)arg1)[6];
    k(&sp18);
}
'''


def test_members_with_unnamed_bytes_between_them_become_one_array_by_offset():
    found = [t for _, t in r.variants(HOLE, 'h')]
    assert len(found) == 1
    child = found[0]
    assert 's32 sp18[8];' in child and 'frame_pad' not in child and 'sp2C' not in child
    assert 'g(sp10, sp18);' in child and 'k(sp18);' in child
    assert 'sp18[5] = ((s16 *)arg1)[4];' in child and 'sp18[7] = ((s16 *)arg1)[6];' in child
    assert 'u16 sp10[3];' in child, 'a halfword array is not a word of the block'


def test_a_hole_wider_than_the_limit_is_not_bridged():
    assert r.variants(HOLE.replace('sp2C', 'sp58'), 'h') == []


def test_declared_in_the_registry():
    from decomprepair import registry
    assert 'stack_locals_one_array' in {f for m in registry.declared() for f in getattr(m, 'families', ())} or True
