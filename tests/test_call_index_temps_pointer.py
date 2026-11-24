"""call_index_temps_pointer: m2c's index temporaries put back into their call, the record read through one pointer."""

from decomprepair import call_index_temps_pointer as m

SOURCE = """typedef unsigned short u16;
typedef int s32;
void plane(float *out, s32 a, s32 b, s32 c);
void f(float *out, char *tris, s32 verts, s32 i)
{
  s32 a1;
  unsigned int a2;
  u16 v0;
  a2 = (*((u16 *) (((char *) (tris + (i * 6))) + 2))) * 3; v0 = *((u16 *) (((char *) (tris + (i * 6))) + 4)); a1 = verts + ((*((u16 *) (((char *) (tris + (i * 6))) + 0))) * 0xC);
  plane(out, a1, verts + (a2 * 4), verts + (v0 * 0xC));
}
"""


def test_the_temporaries_go_back_and_the_record_is_a_pointer():
    [(family, text)] = m.variants(SOURCE, 'f')
    assert family == m.FAMILY
    assert 'record_u16 = (u16 *) (tris + (i * 6));' in text
    assert 'record_u16[0] * 0xC' in text and 'record_u16[1] * 0xC' in text and 'record_u16[2] * 0xC' in text
    assert '* 3' not in text and 'a2 =' not in text
    assert 'u16 *record_u16;' in text


def test_a_temporary_used_again_later_stays():
    again = SOURCE.replace('verts + (v0 * 0xC));', 'verts + (v0 * 0xC));\n  plane(out, v0, 0, 0);')
    assert m.variants(again, 'f') == [] or 'v0 =' in m.variants(again, 'f')[0][1]


def test_a_single_assignment_before_a_call_is_left_alone():
    one = 'void g(int);\nvoid f(int x)\n{\n  int t;\n  t = x * 3;\n  g(t * 4);\n}\n'
    assert m.variants(one, 'f') == []
