"""A byte value masked twice: a halfword local set from `(u8) (x & M)`, its copies uncast, its results halfwords."""
from decomprepair.byte_mask_halfword_local import FAMILY, REPAIR, variants

SAVED = '''void f(u32 *sp, u8 *s, s32 n)
{
  u32 temp;
  s32 lo;
  int v;
  unsigned b3;
  u8 b4;
  if (n != 0)
  {
    temp = sp[1] & 0x3F; b4 = temp & 0xFF;
    lo = (u8) (b4 & 0x1F);
    g(s, b4 >> 5, lo);
    s[0x3f] = b4;
    b4 = lo;
    v = b4 + n;
  }
  else
  {
    b4 = (sp[1] & 3) & 0xFF;
    v = (b4 + n) | 0x8000;
  }
  b3 = (sp[0] & 0x3F) & 0xFF;
  s[0x3e] = b3;
  *((s16 *) (s + 0x4a)) = v;
  temp = n;
  s[0] = temp;
}
'''


def _squash(text):
    return ' '.join(text.split())


def _children(source):
    return [_squash(src) for fam, src in variants(source, 'f') if fam == FAMILY]


def test_byte_locals_become_halfwords_set_through_a_byte_cast():
    first = _children(SAVED)[0]
    assert 'u16 b3; u16 b4;' in first
    assert 'b4 = (u8) (sp[1] & 0x3F); lo =' in first  # the staging statement goes, temp is set again later
    assert 'b4 = (u8) (sp[1] & 3);' in first and 'b3 = (u8) (sp[0] & 0x3F);' in first
    assert 's32 lo;' in first and 'lo = (u8) (b4 & 0x1F);' in first  # a wide copy is not a byte local
    assert 'int v;' in first


def test_the_measured_child_uncasts_the_copy_and_narrows_the_halfword_result():
    children = _children(SAVED)
    assert 'lo = (b4 & 0x1F);' in children[1] and 'int v;' in children[1]
    third = children[2]
    assert 'lo = (b4 & 0x1F);' in third and 's16 v;' in third and 'u16 b3; u16 b4;' in third


def test_each_local_alone_when_there_are_several():
    children = _children(SAVED)
    assert any('unsigned b3; u16 b4;' in c for c in children[3:])
    assert any('u16 b3; u8 b4;' in c for c in children[3:])


def test_a_staging_temporary_read_later_is_left_alone():
    source = SAVED.replace('temp = n;\n  s[0] = temp;', 's[0] = temp;')
    first = _children(source)[0]
    assert 'temp = sp[1] & 0x3F; b4 = temp & 0xFF;' in first
    assert 'b4 = (u8) (sp[1] & 3);' in first


def test_nothing_without_a_byte_mask():
    assert _children('void f(u32 x, u8 *s)\n{\n  u8 b;\n  b = x & 0x3F;\n  s[0] = b;\n}\n') == []
    assert _children('void f(u32 x, u8 *s)\n{\n  u8 b;\n  b = (x & 0x1FF) & 0xFF;\n  s[0] = b;\n}\n') == []


def test_declared_for_the_registry():
    assert REPAIR['families'] == (FAMILY,) and REPAIR['archs'] == ('mips',)
    assert REPAIR['variants'] is variants
