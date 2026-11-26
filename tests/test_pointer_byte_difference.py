"""A pointer minus an integer address is scaled by the element size; the byte length needs the pointer cast."""
from decomprepair import pointer_byte_difference as p

SOURCE = '''typedef int s32;
extern char D_800FFC70[];
extern char D_801086C1[];
extern s32 func_800CE950;
extern s32 func_800FF7E8;
s32 osInvalICache();
s32 osInvalDCache();

void f(void) {
    s32 *base;
    char *tail;
    s32 *temp;
    base = &func_800FF7E8;
    temp = base + 0xF6;
    osInvalICache(&func_800CE950, temp - (s32) &func_800CE950);
    tail = D_801086C1;
    osInvalDCache(D_800FFC70, tail - (s32) &D_800FFC70);
}
'''


def test_a_word_pointer_gets_the_byte_difference_and_a_char_pointer_is_left_alone():
    children = p.variants(SOURCE, 'f')
    assert [family for family, _ in children] == [p.FAMILY]
    assert 'osInvalICache(&func_800CE950, (s32) temp - (s32) &func_800CE950);' in children[0][1]
    assert 'tail - (s32) &D_800FFC70' in children[0][1]


def test_an_array_symbol_and_several_sites_give_an_all_child():
    source = SOURCE.replace('extern char D_801086C1[];', 'extern s32 D_801086C1[];').replace(
        'osInvalDCache(D_800FFC70, tail -', 'osInvalDCache(D_800FFC70, D_801086C1 -')
    children = p.variants(source, 'f')
    assert [family for family, _ in children] == [p.FAMILY, p.FAMILY, p.FAMILY_ALL]
    assert '(s32) D_801086C1 - (s32) &D_800FFC70' in children[1][1]
    assert children[2][1].count('(s32) temp -') == 1 and '(s32) D_801086C1 -' in children[2][1]


def test_a_product_or_an_already_cast_pointer_is_not_a_site():
    assert p.variants(SOURCE.replace('temp - (s32)', '(s32) temp - (s32)'), 'f') == []
    assert p.variants(SOURCE.replace('temp - (s32) &func_800CE950', 'base * temp - (s32) &func_800CE950'), 'f') == []
    assert p.variants(SOURCE.replace('s32 *temp;', 's32 temp;'), 'f') == []
