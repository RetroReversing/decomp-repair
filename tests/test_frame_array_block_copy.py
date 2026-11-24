"""frame_array_block_copy: consecutive frame-array elements stored through a pointer, as one struct copy."""

from decomprepair import frame_array_block_copy as m

SOURCE = """typedef float f32;
typedef struct { f32 v; } Field_f32;
#define spF8 plane[0]
#define spFC plane[1]
#define sp100 plane[2]
#define sp104 plane[3]
void make(f32 *);
void f(void *out)
{
  f32 plane[4];
  make(plane);
  ((Field_f32 *) (((char *) out) + 0))->v = spF8;
  ((Field_f32 *) (((char *) out) + 4))->v = spFC;
  ((Field_f32 *) (((char *) out) + 8))->v = sp100;
  ((Field_f32 *) (((char *) out) + 0xC))->v = sp104;
}
"""


def test_the_run_is_one_struct_copy():
    [(family, text)] = m.variants(SOURCE, 'f')
    assert family == m.FAMILY
    assert '*((Block4_f32 *) out) = *((Block4_f32 *) (&plane[0]));' in text
    assert 'typedef struct { f32 v[4]; } Block4_f32;\nvoid f(void *out)' in text
    assert '->v = sp' not in text


def test_m2c_field_spelling_and_an_offset():
    src = SOURCE.replace('((Field_f32 *) (((char *) out) + 0))->v', 'M2C_FIELD(out, f32 *, 0x10)').replace(
        '((Field_f32 *) (((char *) out) + 4))->v', 'M2C_FIELD(out, f32 *, 0x14)')
    texts = [t for _, t in m.variants(src, 'f')]
    assert any('*((Block2_f32 *) (((char *) out) + 0x10)) = *((Block2_f32 *) (&plane[0]));' in t for t in texts)


def test_elements_out_of_order_are_not_a_copy():
    src = SOURCE.replace('= spFC;', '= sp104;\n  ((Field_f32 *) (((char *) out) + 0x10))->v = spFC;').replace(
        '((Field_f32 *) (((char *) out) + 8))->v = sp100;\n  ((Field_f32 *) (((char *) out) + 0xC))->v = sp104;\n', '')
    assert m.variants(src, 'f') == []
