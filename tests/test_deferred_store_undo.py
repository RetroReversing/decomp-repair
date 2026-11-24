"""deferred_store_undo: temporaries stored in the same order written as the direct stores."""

from decomprepair import deferred_store_undo as m

SOURCE = """typedef float f32;
void f(f32 *out, f32 *in, f32 d)
{
  f32 a;
  f32 b;
  a = in[0];
  b = in[1] - d;
  out[0] = a;
  out[1] = b;
  out[2] = in[2];
}
"""


def test_the_run_becomes_direct_stores():
    [(fam, text)] = m.variants(SOURCE, 'f')
    assert fam == m.FAMILY
    assert '  out[0] = in[0];\n  out[1] = in[1] - d;\n  out[2] = in[2];' in text
    assert 'f32 a;' not in text and 'f32 b;' not in text


def test_a_temporary_used_again_stays():
    again = SOURCE.replace('  out[2] = in[2];', '  out[2] = a;')
    assert m.variants(again, 'f') == []
