"""A volatile global array the function only indexes is declared plain."""
from decomprepair import volatile_array_plain_repairs as p

SOURCE = '''typedef short s16;
extern volatile s16 table[4];
extern s16 other[4];
extern s16 volatile second[4];

void f(int i)
{
  table[i] = 0;
  other[i] = 1;
  second[i] = 2;
}
'''


def test_each_volatile_array_gets_a_child_and_all_of_them_one_more():
    children = p.variants(SOURCE, 'f')
    assert [family for family, _ in children] == [p.FAMILY, p.FAMILY, p.FAMILY_ALL]
    assert 'extern s16 table[4];' in children[0][1] and 'volatile s16 second' not in children[1][1]
    assert 'volatile' in children[0][1] and 'volatile' not in children[2][1]


def test_an_array_whose_address_or_bare_name_escapes_keeps_volatile():
    assert p.variants(SOURCE.replace('table[i] = 0;', 'g(&table[0]);'), 'f')[0][1].count('volatile') == 1
    assert p.variants(SOURCE.replace('table[i] = 0;', 'g(table);'), 'f')[0][1].count('volatile') == 1


def test_an_array_the_function_does_not_use_is_left_alone():
    assert p.variants(SOURCE.replace('table[i] = 0;', ''), 'f')[0][1].count('volatile') == 1
