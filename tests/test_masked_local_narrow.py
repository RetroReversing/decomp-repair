from decomprepair import masked_local_narrow as r

SOURCE = '''extern u16 gFlags[];
extern s32 gTable[];
extern void use(s32);

void f(s32 i)
{
  register s32 index;
  s32 wide;
  s32 level;
  u16 raw;

  raw = gFlags[i];
  index = raw & 0xF;
  if (index != 0)
  {
    use(gTable[index]);
  }
  wide = raw & 0xFFFF;
  level = raw & 0x3;
  level = level + 1;
  use(wide + level);
}
'''


def children(source=SOURCE):
    return [text for fam, text in r.variants(source, 'f') if fam == 'masked_local_narrow']


def test_a_local_set_only_from_a_mask_gets_the_type_the_mask_fits():
    out = children()
    assert any('register u8 index;' in t and 's32 wide;' in t for t in out)
    assert any('u16 wide;' in t and 'register s32 index;' in t for t in out)
    everything = out[-1]
    assert 'register u8 index;' in everything and 'u16 wide;' in everything


def test_a_local_with_another_kind_of_assignment_is_left_alone():
    assert all('s32 level;' in t for t in children())  # (level = level + 1 is not a masked value)


def test_an_address_taken_or_incremented_local_is_left_alone():
    taken = SOURCE.replace('use(gTable[index]);', 'use(*(&index));')
    assert all('register s32 index;' in t for t in children(taken))
    stepped = SOURCE.replace('use(gTable[index]);', 'index++;')
    assert all('register s32 index;' in t for t in children(stepped))


def test_a_mask_wider_than_a_halfword_is_left_alone():
    assert all('s32 wide;' in t for t in children(SOURCE.replace('raw & 0xFFFF', 'raw & 0x1FFFF')))


def test_the_name_is_kept_and_nothing_else_changes():
    out = children()[0]
    assert 'index = raw & 0xF;' in out and out.count('use(') == 3
