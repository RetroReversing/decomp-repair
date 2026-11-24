"""constant_guard_flag: m2c's `if (0 == 0) goto L;` written back as a NULL flag test, with the copies it guards."""

from decomprepair import constant_guard_flag as m

SOURCE = """typedef float f32;
typedef struct { f32 v; } Field_f32;
typedef struct
{
  f32 x;
  f32 y;
  f32 z;
} Vec;
#define sp28 start[0]
#define sp2C start[1]
#define sp30 start[2]
#define sp180 hit[0]
int f(void *p, void *out, void *other, f32 limit)
{
  f32 start[3];
  f32 hit[3];
  f32 best;
  best = limit;
  if (p != 0)
  {
    if (best == limit)
    {
      if (0 == 0)
      {
        goto block_245;
      }
      ((Field_f32 *) (((char *) out) + 0))->v = sp28;
      ((Field_f32 *) (((char *) out) + 4))->v = sp2C;
      ((Field_f32 *) (((char *) out) + 8))->v = sp30;
      goto block_247;
    }
    *((Vec *) other) = *((Vec *) (&sp180));
    block_247:
    return 1;
  }
  block_245:
  return 0;
}
"""


def test_the_flag_test_and_the_moved_copy_as_a_word_copy():
    children = m.variants(SOURCE, 'f')
    fam, text = children[0]
    assert fam == m.COMBINED
    assert 'if (0 == 0)' not in text and 'goto check_found;' in text
    assert 'check_found:\n  if (found == NULL)\n  {\n    return 0;\n  }' in text
    assert '*((Block3_f32 *) out) = *((Block3_f32 *) (&start[0]));' in text
    assert '((Field_f32 *) (((char *) other) + 4))->v = hit[1];' in text
    assert 'found = NULL;\n  best = limit;' in text


def test_the_flag_alone_is_a_child():
    plain = [t for fam, t in m.variants(SOURCE, 'f') if fam == m.FAMILY]
    assert plain and all('*((Vec *) other) = *((Vec *) (&sp180));' in t for t in plain)


def test_no_guard_no_children():
    assert m.variants(SOURCE.replace('if (0 == 0)', 'if (best != 0)'), 'f') == []
