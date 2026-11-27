from decomprepair import constant_store_chain as module

SOURCE = '''void run(u8 *p)
{
  s32 i;
  i = 0x40;
  *(u16 *) (p + 8) = 0x40;
  *(u16 *) (p + 6) = 0x40;
  *(u16 *) (D_80000000 + (i * 100)) = 0x40;
  p->x = 0;
  if (p[0] == 0x40) { p[1] = 2; p[2] = 3; }
}
'''


def test_adjacent_stores_of_one_constant_become_a_chain_in_the_same_order():
    texts = [text for family, text in module.variants(SOURCE, 'run') if family == module.FAMILY]
    chain = '*(u16 *) (D_80000000 + (i * 100)) = *(u16 *) (p + 6) = *(u16 *) (p + 8) = 0x40;'
    assert any(chain in text and 'i = 0x40;' in text for text in texts)
    assert all('p->x = 0;' in text for text in texts)


def test_different_constants_and_lone_stores_are_left_alone():
    for _, text in module.variants(SOURCE, 'run'):
        assert 'p[1] = 2; p[2] = 3;' in text
    assert module.variants('void run(s32 *p) { p[0] = 1; p[1] = 2; }', 'run') == []
