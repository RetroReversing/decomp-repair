from decomprepair import registry
from decomprepair import sibling_constant_holder as repairs

SOURCE = '''void f(void *arg0) {
    void *a;
    void *b;
    a = g();
    if (a != 0) {
        M2C_FIELD(a, s8 *, 0x78) = 2;
        M2C_FIELD(a, s8 *, 0x73) = 0;
        M2C_FIELD(a, s32 *, 0x80) = 0x408;
    }
    b = g();
    if (b != 0) {
        M2C_FIELD(b, s8 *, 0x78) = 3;
        M2C_FIELD(b, s8 *, 0x73) = 0;
        M2C_FIELD(b, s32 *, 0x80) = 0x408;
    }
}
'''


def test_both_blocks_literals_go_through_one_local():
    family, text = repairs.variants(SOURCE, 'f')[0]
    assert family == repairs.FAMILY
    assert text.count('s32 held;') == 1
    assert 'held = 2;\n        M2C_FIELD(a, s8 *, 0x78) = held;' in text
    assert 'held = 3;\n        M2C_FIELD(b, s8 *, 0x78) = held;' in text
    assert text.count('held = 0x408;') == 2
    # a zero is $zero in the target: it is not held
    assert 'M2C_FIELD(a, s8 *, 0x73) = 0;' in text


def test_each_subset_of_places_is_a_child():
    assert len(repairs.variants(SOURCE, 'f')) == 3


def test_members_through_different_pointers_are_one_place():
    source = '''void f(T *a, T *b) {
    s32 held;
    if (a) { a->state = 2; }
    if (b) { b->state = 3; }
}
'''
    text = repairs.variants(source, 'f')[0][1]
    assert 's32 held2;' in text and 'held2 = 2; a->state = held2;' in text


def test_one_block_or_unrelated_blocks_offer_nothing():
    assert repairs.variants('void f(T *a) { if (a) { a->x = 1; } }', 'f') == []
    assert repairs.variants('void f(T *a) { if (a) { a->x = 1; } if (a) { a->y = 2; } }', 'f') == []


def test_declared_to_the_registry():
    assert repairs.FAMILY in registry.get('sibling_constant_holder').families
