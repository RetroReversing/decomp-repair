"""loop_preheader_role_reuse: a scale loop's truncation, constant and bound given to earlier locals, as one child.

Synthetic shape of a 207-instruction KMC text-layout function (saved best 15 -> 0 with the one child; each step alone
55, 325 or 60). A sentence loop's flag, a line loop's start pointer and counter, and a last loop over a table."""
import re

from decomprepair import loop_preheader_role_reuse as r
from decomprepair import registry

SOURCE = '''void layout(u8 *text, s32 width, s32 lines, f32 size)
{
  char line[0x200];
  s8 out[0x208];
  f32 scale_f;
  s16 count;
  s32 flag;
  s32 n;
  s32 done;
  s32 i;
  s8 *start;
  s8 *p;
  s32 len;
  void *obj;
  done = 0;
  do
  {
    flag = 0;
    if (*text == '.')
    {
      flag = 1;
    }
    if (flag != 0)
    {
      done = 1;
    }
    text++;
  }
  while (done == 0);
  p = out;
  while (*p != 0)
  {
    n = 0;
    start = p;
    scan:
    p++;
    flag = *p == 0;
    if (flag | (n >= lines))
    {
      len = p - start;
      memcpy(line, start, len);
    }
    ++n;
  }
  count = G;
  if (count != 0)
  {
    scale_f = size / ((f32) count);
    i = 0;
    if (count > 0)
    {
      do
      {
        obj = ((void **) &T)[i];
        if (obj != NULL)
        {
          *((s16 *) (((char *) obj) + 0x30)) = (s16) ((s32) scale_f);
          *((f32 *) (((char *) obj) + 0x14)) = (f32) (4096.0f / scale_f);
        }
        i += 1;
      }
      while (i < count);
    }
  }
}
'''


def _first():
    out = r.variants(SOURCE, 'layout')
    assert out and all(family == r.FAMILY for family, _ in out)
    return out[0][1]


def test_the_four_steps_are_one_child():
    text = _first()
    # the flag holds the truncation, set before the do; the store reads it
    assert re.search(r'flag = \(s32\) scale_f;\n\s*scale = 4096\.0f;\n\s*start = n;\n\s*do', text)
    assert '(s16) flag;' in text and '(s16) ((s32) scale_f)' not in text
    # the constant is read from its local, the bound from the start pointer's variable
    assert '(f32) (scale / scale_f)' in text and 'while (i < start);' in text
    # the start pointer is a word now, read through casts where it was a pointer
    assert 's32 start;' in text and 'start = (s32) p;' in text and 'memcpy(line, ((s8 *) start), len);' in text
    # the count is the line counter, keeping the s16 global's sign extension
    assert 'n = (s16) G;' in text and 's16 count;' not in text and 'if (n > 0)' in text


def test_the_flag_s_later_web_gets_a_fresh_local():
    text = _first()
    assert 's32 flag_late;' in text and 'flag_late = *p == 0;' in text and 'if (flag_late | (n >= lines))' in text
    # the sentence loop keeps the flag itself
    assert 'flag = 1;' in text and 'if (flag != 0)' in text


def test_nothing_without_a_truncated_float_in_a_counted_loop():
    plain = SOURCE.replace('(s16) ((s32) scale_f)', '(s16) i')
    assert r.variants(plain, 'layout') == []
    assert r.variants(SOURCE.replace('while (i < count);', 'while (i != count);'), 'layout') == []


def test_the_module_declares_itself():
    assert any(repair.module.endswith('loop_preheader_role_reuse') for repair in registry.declared())
