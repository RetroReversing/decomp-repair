"""A wide mask staged in a block local that the `and` sets again."""
from decomprepair.mask_local_twice_set import FAMILY, variants

# A projectile update's target reset (KMC GCC 2.7.2, N64): two flag words cleared before a call.
TEXT = '''void f(void)
{
  g((s32) (gTargetObject + 0x24));
  (*(s32 *)((char *)(gTargetObject) + 0x58)) &= -0x1C1;
  (*(s32 *)((char *)(gTargetObject) + 0x50)) &= 0x7F;
  h(gTargetObject, 0);
}
'''


def _children(text):
    return [src for fam, src in variants(text, 'f') if fam == FAMILY]


def test_a_wide_mask_is_staged():
    lhs = '(*(s32 *)((char *)(gTargetObject) + 0x58))'
    want = TEXT.replace(f'{lhs} &= -0x1C1;', f'{{ s32 andMask = -0x1C1; andMask &= {lhs}; {lhs} = andMask; }}')
    assert _children(TEXT) == [want]


def test_each_site_and_all_of_them():
    text = TEXT.replace('&= 0x7F;', '&= ~0x80;')
    kids = _children(text)
    assert len(kids) == 3 and kids[-1].count('andMask = ') == 2


def test_a_mask_andi_takes_or_a_call_is_left_alone():
    assert _children(TEXT.replace('-0x1C1', '0xFE3F')) == []
    assert _children(TEXT.replace('(*(s32 *)((char *)(gTargetObject) + 0x58))', 'obj()->flags')) == []
