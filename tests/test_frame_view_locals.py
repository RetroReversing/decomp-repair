"""frame_view_locals: m2c's frame union written as the locals and arrays it stands for.

Synthetic shape of a 525-instruction KMC display-list builder whose union, vectors and pointer table went through
`m2c_initial_frame` (3551 -> 3099 with this step alone)."""
from decomprepair import frame_view_locals as s

SOURCE = '''s32 load(f32 *);
s32 *get(s32);
void draw(s32 *idx) {
  union
  {
    unsigned char bytes[48];
    struct
    {
      f32 value;
    } view_sp28;
    struct
    {
      unsigned char pad[4];
      f32 value;
    } view_sp2C;
    struct
    {
      unsigned char pad[16];
      s32 value;
    } view_sp38;
    struct
    {
      unsigned char pad[20];
      s32 value;
    } view_sp3C;
    f32 view_sp40_value;
    struct
    {
      unsigned char pad[31];
      u8 value;
    } view_sp47;
  } m2c_initial_frame;
  s32 *t;
  load(&m2c_initial_frame.view_sp28.value);
  m2c_initial_frame.view_sp38.value = (s32) get(1);
  m2c_initial_frame.view_sp3C.value = (s32) get(2);
  m2c_initial_frame.view_sp40_value = m2c_initial_frame.view_sp2C.value * 2.0f;
  m2c_initial_frame.view_sp47.value = 0xFF;
  t = *((s32 **) (((char *) (&(&m2c_initial_frame.view_sp28.value)[*idx])) + 0x10));
  *t = m2c_initial_frame.view_sp47.value;
}
'''


def test_views_become_arrays_and_scalars_in_frame_order():
    texts = [text for family, text in s.variants(SOURCE, 'draw')]
    assert len(texts) == 2 and all('m2c_initial_frame' not in t for t in texts)
    filled, tight = texts
    assert 'f32 sp28[4];\n  s32 sp38[2];\n  f32 sp40;\n  u8 sp47;' in filled
    assert 'f32 sp28[2];\n  s32 sp38[2];' in tight
    assert 'load(sp28);' in filled
    assert 'sp38[0] = (s32) get(1);' in filled and 'sp38[1] = (s32) get(2);' in filled
    assert 'sp40 = sp28[1] * 2.0f;' in filled and 'sp47 = 0xFF;' in filled
    assert 't = *((s32 **) (((char *) &sp38[*idx])));' in filled


def test_a_bytes_read_or_an_overlap_declines():
    assert s.variants(SOURCE.replace('*t = m2c_initial_frame.view_sp47.value;', '*t = m2c_initial_frame.bytes[3];'), 'draw') == []
    overlap = SOURCE.replace('f32 view_sp40_value;', 'f32 view_sp40_value;\n    s32 view_sp42_value;')
    assert s.variants(overlap, 'draw') == []


def test_a_function_without_the_union_is_left_alone():
    assert s.variants('void f(void) { int a; a = 1; }', 'f') == []


def test_the_module_declares_itself():
    assert s.REPAIR['families'] == (s.FAMILY,)
