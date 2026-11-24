"""call_operand_load_inline: a load only the next call statement reads, written in the call's operands."""

from decomprepair import call_operand_load_inline as m

SOURCE = """typedef struct { int v; } Field_s32;
int hit(int a, int b, int c);
void seg(int a, int b);
void f(char *rec, unsigned short *t)
{
  int v;
  int w;
  v = ((Field_s32 *) (rec + 0x34))->v;
  if (hit(v + (t[0] * 12), v + (t[1] * 12), v + (t[2] * 12)) & 0xFF)
  {
    w = ((Field_s32 *) (rec + 0x34))->v;
    seg(w + (t[0] * 12), w + (t[1] * 12));
  }
}
"""


def test_both_loads_go_into_their_calls_together():
    fam, text = m.variants(SOURCE, 'f')[0]
    assert fam == m.COMBINED
    assert 'if (hit((((Field_s32 *) (rec + 0x34))->v) + (t[0] * 12),' in text
    assert 'seg((((Field_s32 *) (rec + 0x34))->v) + (t[0] * 12),' in text
    assert '  int v;' not in text and '  int w;' not in text


def test_a_temporary_read_again_later_stays():
    later = SOURCE.replace('seg(w + (t[0] * 12), w + (t[1] * 12));', 'seg(w + (t[0] * 12), w + (t[1] * 12));\n    seg(v, 0);')
    texts = [t for _, t in m.variants(later, 'f')]
    assert texts and all('v = ((Field_s32 *) (rec + 0x34))->v;' in t for t in texts)
