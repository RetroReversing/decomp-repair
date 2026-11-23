"""A sum cast to the narrow store's type."""
from decomprepair.narrow_sum_operand_cast import FAMILY, FAMILY_ALL, variants

SAVED = '''extern u16 W;
extern u16 table[];
void f(char *q, s16 x, s32 i)
{
    (*(u16 *)((char *)q + 0x20)) = W + (x + 0xFFC7U);
    table[i] = W + (x + 0xFFDBU);
}
'''


def _children(source, family=FAMILY):
    return [src for fam, src in variants(source, 'f') if fam == family]


def test_the_inner_sum_of_a_halfword_store_is_cast_to_the_store_type():
    out = _children(SAVED)
    assert len(out) == 2
    assert 'W + (u16) (x + 0xFFC7U);' in out[0] or 'W + (u16) (x + 0xFFC7U);' in out[1]
    assert any('table[i] = W + (u16) (x + 0xFFDBU);' in c for c in out)


def test_every_statement_together_is_one_more_child():
    both = _children(SAVED, FAMILY_ALL)
    assert len(both) == 1
    assert both[0].count('(u16) (x + ') == 2


def test_a_store_of_a_word_or_an_existing_cast_gives_no_child():
    assert variants(SAVED.replace('(*(u16 *)', '(*(u32 *)').replace('table[i]', 'other[i]'), 'f') == []
    already = SAVED.replace('W + (x + 0xFFC7U)', 'W + (u16) (x + 0xFFC7U)').replace('table[i] =', 'other[i] =')
    assert variants(already, 'f') == []


def test_a_sum_without_a_literal_is_left_alone():
    assert variants(SAVED.replace('0xFFC7U', 'y').replace('0xFFDBU', 'z').replace('table[i]', 'other[i]'), 'f') == []
