"""A contiguous word clear written as a compound clear of a wider bit-field member."""
from decomprepair.bitfield_member_clear import FAMILY, variants

# A projectile update's target reset (KMC GCC 2.7.2, N64): two flag words cleared before a call.
LHS = '(*(s32 *)((char *)(gTargetObject) + 0x58))'
TEXT = f'''void f(void)
{{
  g((s32) (gTargetObject + 0x24));
  {LHS} &= -0x1C1;
  (*(s32 *)((char *)(gTargetObject) + 0x50)) &= 0x7F;
  h(gTargetObject, 0);
}}
'''


def _children(text):
    return [src for fam, src in variants(text, 'f') if fam == FAMILY]


def test_each_wider_layout_is_offered():
    kids = _children(TEXT)
    assert len(kids) == 3
    assert 'struct MaskField0 { u32 hi:22; u32 f:4; u32 lo:6; };' in kids[0]
    assert '((struct MaskField0 *)((char *)(gTargetObject) + 0x58))->f &= ~0x7;' in kids[0]
    assert 'struct MaskField1 { u32 hi:22; u32 f:4; u32 lo:5; };' not in kids[1]
    assert '->f &= ~0xE;' in kids[1] and '->f &= ~0x1C0;' in kids[2]
    assert all(LHS + ' &=' not in kid for kid in kids)


def test_the_staged_mask_is_rewritten_too():
    staged = TEXT.replace(f'{LHS} &= -0x1C1;', f'{{ s32 andMask = -0x1C1; andMask &= {LHS}; {LHS} = andMask; }}')
    assert _children(staged) == _children(TEXT)


def test_masks_it_cannot_use_are_left_alone():
    assert _children(TEXT.replace('-0x1C1', '0xFE3F')) == []      # andi takes it
    assert _children(TEXT.replace('-0x1C1', '-0x1C5')) == []      # two runs of bits
    assert _children(TEXT.replace('-0x1C1', '0x7FFFFFFF')) == []  # bit 31
    assert _children(TEXT.replace(LHS, 'obj->flags')) == []
