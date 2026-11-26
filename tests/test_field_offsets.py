"""Struct fields moved to where the target has them: read from offsets, never judged here."""
from decomprepair import field_offsets as fo
from decomprepair import registry

DONOR = '''typedef struct Actor {
    s16 kind;
    s16 hp;
    f32 x;
    struct Actor *next;
} Actor;
s32 actor_hp(Actor *a) { return a->hp + a->next->hp; }
'''


def word(op, rs, rt, imm):
    return ((op << 26) | (rs << 21) | (rt << 16) | (imm & 0xffff)).to_bytes(4, 'big')


def test_layout_follows_mips_o32_sizes_and_alignment():
    types = fo.Types(DONOR)
    actor = types.struct('Actor')
    assert [(m.name, m.offset) for m in actor.members] == [('kind', 0), ('hp', 2), ('x', 4), ('next', 8)]
    assert (actor.size, actor.align) == (12, 4)
    padded = fo.Types('struct P { u8 a; f64 d; u16 e[3]; };').struct('struct P')
    assert [(m.name, m.offset) for m in padded.members] == [('a', 0), ('d', 8), ('e', 16)] and padded.size == 24
    assert fo.Types('struct B { int a : 3; };').struct('B') is None  # bitfields are not laid out here
    assert fo.Types('struct U { Unknown u; };').struct('U') is None


def test_pairs_reads_only_struct_load_store_offsets_that_differ():
    compiled = word(33, 4, 2, 2) + word(35, 29, 3, 16) + word(9, 4, 4, 2)  # lh v0,2(a0); lw v1,16(sp); addiu
    target = word(33, 4, 2, 6) + word(35, 29, 3, 20) + word(9, 4, 4, 6)
    assert fo.pairs(compiled, target, set(), True) == {2: 6}
    assert fo.pairs(compiled, target, {0}, True) == {}
    assert fo.pairs(compiled, target[:4], set(), True) == {}
    conflicting = word(33, 4, 2, 2) + word(33, 5, 2, 2)
    assert fo.pairs(conflicting, word(33, 4, 2, 6) + word(33, 5, 2, 8), set(), True) == {}


def test_from_pairs_lays_the_struct_out_again_and_rewrites_the_uses():
    relaid, rewritten = fo.from_pairs(DONOR, '', {2: 6})
    assert 's16 kind;\n    char _pad0[0x4];\n    s16 hp;' in relaid and 'char _pad1[0x2];' not in relaid
    assert '} Actor;' in relaid and 'return a->hp + a->next->hp;' in relaid
    laid = fo.Types(relaid).struct('Actor')
    assert {m.name: m.offset for m in laid.members if not m.name.startswith('_pad')} == {'kind': 0, 'hp': 6, 'x': 8, 'next': 12} and laid.size == 16
    assert 'return (*(s16 *)((char *)a + 0x6)) + a->next->hp;' in rewritten


def test_a_struct_in_the_header_gets_only_the_rewritten_uses():
    header, function = DONOR.split('s32 actor_hp')
    out = fo.from_pairs('s32 actor_hp' + function, header, {2: 6})
    assert out == ['s32 actor_hp(Actor *a) { return (*(s16 *)((char *)a + 0x6)) + a->next->hp; }\n']


def test_nothing_when_fields_would_overlap_or_the_offset_is_ambiguous():
    assert fo.from_pairs(DONOR, '', {4: 2}) == [] or all('_pad' not in t for t in fo.from_pairs(DONOR, '', {4: 2}))
    overlap = fo.from_pairs(DONOR, '', {2: 5})  # misaligned for an s16
    assert all('_pad' not in text for text in overlap)
    two = 'typedef struct A { s32 a; s32 b; } A;\ntypedef struct B { s32 c; s32 d; } B;\n' \
          'int f(A *p, B *q) { return p->b + q->d; }'
    assert fo.from_pairs(two, '', {4: 8}) == []


def test_variants_pair_the_targets_offsets_in_order_and_are_declared():
    asm = '/* 0 */ lh $v0, 0x6($a0)\n/* 4 */ lw $v1, 0xc($a0)\n/* 8 */ lh $v1, 0x6($v1)\n/* c */ lw $t0, 0x18($sp)\n'
    found = fo.variants(DONOR, 'actor_hp', '', asm)
    assert found and all(family == fo.FAMILY for family, _ in found)
    laid = fo.Types(found[0][1]).struct('Actor')
    assert {m.name: m.offset for m in laid.members if not m.name.startswith('_pad')} == {'kind': 0, 'hp': 6, 'x': 8, 'next': 12}
    assert fo.variants(DONOR, 'actor_hp', '', asm.replace('0x6', '0x2').replace('0xc', '0x8')) == []
    entry = registry.get('field_offsets')
    assert entry is not None and registry.problems(entry) == []
