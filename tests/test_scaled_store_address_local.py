"""A byte store at `base[K + (index * S)]` written through a pointer local holding the scaled address."""
from decomprepair import registry
from decomprepair import scaled_store_address_local as p

SOURCE = '''typedef unsigned char u8;
extern short table[];

int mark(u8 *object, int id)
{
    short i;
    i = table[id];
    if (i != -1) {
        object[0x1fc + (i * 8)] = 1;
    }
    return 0;
}
'''


def test_one_store_goes_through_a_pointer_local():
    families = dict(p.variants(SOURCE, 'mark'))
    text = families[p.FAMILY]
    assert 'u8 *addr1;' in text
    assert 'addr1 = object + (i * 8); addr1[0x1fc] = 1;' in text
    assert 'object[0x1fc + (i * 8)]' not in text


def test_the_sum_in_the_other_order_and_a_computed_value():
    source = SOURCE.replace('object[0x1fc + (i * 8)] = 1;', 'object[(i * 8) + 4] = id + 1;')
    text = dict(p.variants(source, 'mark'))[p.FAMILY]
    assert 'addr1 = object + (i * 8); addr1[4] = id + 1;' in text


def test_two_stores_also_make_a_combined_child_with_a_local_each():
    source = SOURCE.replace('object[0x1fc + (i * 8)] = 1;', 'object[0x1fc + (i * 8)] = 1; object[4 + (id * 2)] = 2;')
    children = p.variants(source, 'mark')
    assert [family for family, _ in children] == [p.FAMILY, p.FAMILY, p.FAMILY_ALL]
    combined = children[-1][1]
    assert 'u8 *addr1;' in combined and 'u8 *addr2;' in combined


def test_a_store_that_changes_its_own_index_or_calls_is_left_alone():
    for body in ('object[0x1fc + (i * 8)] = i++;', 'object[0x1fc + (i * 8)] = f(i);', 'object[0x1fc + (i * 8)] = (i = 2);'):
        assert p.variants(SOURCE.replace('object[0x1fc + (i * 8)] = 1;', body), 'mark') == []


def test_a_word_pointer_is_left_alone():
    assert p.variants(SOURCE.replace('u8 *object', 'int *object'), 'mark') == []


def test_it_declares_itself_to_the_registry():
    assert registry.problems(next(r for r in registry.declared() if r.module == 'scaled_store_address_local')) == []
