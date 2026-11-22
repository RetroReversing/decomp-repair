"""A shift added twice: the chain alone merges, the chain with a trailing known-zero use is offered as one child."""
from decomprepair import shared_shift_zero_use as m

SOURCE = '''void f(u8 *h) {
  s32 *buf;
  s32 v;
  buf = alloc(((u32) (((*(u16 *) (h + 0x14)) * 8) + (v = (*(u16 *) (h + 0xC)) * 4))) + ((*(u16 *) (h + 0x1C)) + v), 0x2D);
  use(buf);
}
'''
A, T, C = '(*(u16 *) (h + 0x14))', '(*(u16 *) (h + 0xC))', '(*(u16 *) (h + 0x1C))'


def test_three_children_and_exact_combined_text():
    found = dict(m.variants(SOURCE, 'f'))
    assert set(found) == set(m.FAMILIES)
    chain = f'({A} * 8) + (v = {T} * 4) + v + {C}'
    assert f'alloc({chain} + (v & 3), 0x2D);' in found['shared_shift_combination']
    assert f'alloc({chain}, 0x2D);' in found['shared_shift_chain']
    assert '+ (v & 3), 0x2D);' in found['shared_shift_zero_use'] and '(u32)' in found['shared_shift_zero_use']


def test_guards():
    assert not m.variants(SOURCE.replace('* 4)', '* 3)'), 'f')
    assert not m.variants(SOURCE.replace('+ v)', '+ w)'), 'f')
    assert not m.variants(SOURCE.replace('(*(u16 *) (h + 0x1C))', 'g(1)'), 'f')
