"""chain_weight_scope: a flag chain in one-shot scopes, with the flag's later reuse split off, as one child.

Shape of a 167-instruction KMC function (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2 -fno-strength-reduce`): the
frame-validity flag (`sltu`, `negu`, `and`) took `$v1` and the table index `$v0`; the target has them the other way
round. The split alone 35 -> 45, the scopes alone 35 and 80, both 10, with the row loop's natural form 0."""
from decomprepair import chain_weight_scope as chain

SOURCE = '''typedef struct { s16 limit; s16 shape; s32 base; } Rec;
extern Rec *gRec;
extern s16 gTable[];
void consume(s32, s32, s32);
void f(u32 frame, s32 extra)
{
  s32 flag;
  s32 shape;
  s32 count;
  Rec *rec;
  rec = gRec;
  flag = frame < ((u32) rec->limit);
  shape = rec->shape;
  count = gTable[shape & 0x7fff];
  frame &= -flag;
  shape &= 0x8000;
  consume(count, frame, shape);
  flag = rec->base + extra;
  consume(flag, flag, flag);
}
'''


def test_the_definition_with_its_neighbour_and_the_reader_get_a_scope_each():
    out = [text for family, text in chain.variants(SOURCE, 'f') if family == 'chain_weight_scope']
    assert out
    whole = next(text for text in out if '__repair_phase_flag' not in text and text.count('do {') == 2)
    assert '/*__repair_chain_scope*/do { flag = frame < ((u32) rec->limit);\n  shape = rec->shape; } while (0);' in whole
    assert '/*__repair_chain_scope*/do { frame &= -flag; } while (0);' in whole
    assert 'count = gTable[shape & 0x7fff];' in whole


def test_the_later_reuse_of_the_flag_is_split_in_the_same_child():
    split = [text for _, text in chain.variants(SOURCE, 'f') if '__repair_phase_flag' in text and text.count('do {') == 2]
    assert split
    assert '__repair_phase_flag = rec->base + extra;' in split[0]
    assert 'consume(__repair_phase_flag, __repair_phase_flag, __repair_phase_flag);' in split[0]
    assert 'flag = frame <' in split[0]


def test_every_child_keeps_the_statements_it_wraps():
    for _, text in chain.variants(SOURCE, 'f'):
        for statement in ('count = gTable[shape & 0x7fff];', 'shape &= 0x8000;'):
            assert statement in text
        assert text.count('do {') == text.count('} while (0);') == 2


def test_a_run_of_two_statements_offers_nothing():
    short = '''void f(u32 frame, Rec *rec)
{
  s32 flag;
  s32 count;
  flag = frame < ((u32) rec->limit);
  frame &= -flag;
}
'''
    assert chain.variants(short, 'f') == []
    assert chain.variants('void g(void) { }', 'g') == []


def test_a_scoped_source_is_not_scoped_again():
    scoped = chain.variants(SOURCE, 'f')[0][1]
    assert chain.variants(scoped, 'f') == []
