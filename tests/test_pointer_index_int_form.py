"""An element address `&base[i]` written as an integer sum with the scaled index first."""
from decomprepair import pointer_index_int_form as p

SOURCE = '''typedef short s16;
extern s16 flags[4];

void f(int i, s16 *loaded)
{
  s16 *a;
  s16 *b;
  a = &flags[i];
  b = flags + i;
  *a = 0;
  *b = 1;
}
'''


def test_each_element_address_gets_an_integer_sum_child_and_all_one_more():
    children = p.variants(SOURCE, 'f')
    assert [family for family, _ in children] == [p.FAMILY, p.FAMILY, p.FAMILY_ALL]
    assert 'a = (s16 *) (i * 2 + (s32) flags);' in children[0][1] and 'b = flags + i;' in children[0][1]
    assert 'b = (s16 *) (i * 2 + (s32) flags);' in children[1][1]
    assert 'a = (s16 *) (i * 2 + (s32) flags);' in children[2][1] and 'b = (s16 *) (i * 2 + (s32) flags);' in children[2][1]


def test_a_local_pointer_base_and_a_product_index():
    source = SOURCE.replace('a = &flags[i];', 'a = &loaded[i * 2];')
    text = p.variants(source, 'f')[0][1]
    assert 'a = (s16 *) ((i * 2) * 2 + (s32) loaded);' in text


def test_a_literal_index_or_an_unknown_base_is_left_alone():
    assert p.variants(SOURCE.replace('&flags[i]', '&flags[1]').replace('flags + i', 'flags + 2'), 'f') == []
    assert p.variants(SOURCE.replace('extern s16 flags[4];', '').replace('flags', 'mystery'), 'f') == []


def test_a_pointer_local_initialised_with_the_address():
    source = SOURCE.replace('  s16 *a;\n  s16 *b;\n  a = &flags[i];\n  b = flags + i;', '  s16 *a = &flags[i];\n  s16 *b = flags + i;')
    children = p.variants(source, 'f')
    assert 's16 *a = (s16 *) (i * 2 + (s32) flags);' in children[0][1]
    assert 's16 *b = (s16 *) (i * 2 + (s32) flags);' in children[-1][1]
