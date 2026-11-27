from decomprepair import array_address_rebase

SOURCE = '''extern u8 D_80100000[];
extern u8 D_80100150[];
extern u8 D_80100200[];
void spawn(void *);

void f(void) {
    spawn(D_80100000 + 0x10);
    spawn((void *)D_80100150);
    spawn((void *)D_80100150);
    D_80100200[1] = 0;
}
'''


def test_a_later_table_is_written_from_the_earlier_base():
    children = [child for _, child in array_address_rebase.variants(SOURCE, 'f')]
    assert any(child.count('spawn((void *)(D_80100000 + 0x150));') == 2 for child in children)
    # an indexed array is not an address passed on, so it keeps its name
    assert all('D_80100200[1] = 0;' in child for child in children)


def test_nothing_without_an_earlier_array_in_the_body():
    assert array_address_rebase.variants(SOURCE.replace('D_80100000 + 0x10', '0'), 'f') == []
