"""A table's cursor and byte offset that step with a counter, as reads through the counter."""
from decomprepair import registry
from decomprepair.stepped_cursor_index import FAMILY, variants

# A canonical-code builder's code-assignment pass (KMC GCC 2.7.2, N64).
ASSIGN = '''extern u32 D_800B283C[];
void f(u32 c, u32 *out)
{
  u32 *q;
  u32 i;
  u32 k;
  i = 0;
  k = 0;
  if (c != 0) {
    u32 off = 0;
    q = D_800B283C;
    do {
      if (*q == c) {
        do {
          out[k] = i;
          i++;
          off += 4;
          q++;
          k++;
        } while (D_800B283C[k] == c);
      }
      i *= 2;
      c++;
    } while (*(u32 *)((char *)D_800B283C + off) != 0);
  }
}
'''


def _children(text):
    return [src for fam, src in variants(text, 'f') if fam == FAMILY]


def test_both_become_reads_through_the_counter():
    want = (ASSIGN.replace('    u32 off = 0;\n', '').replace('    q = D_800B283C;\n', '')
            .replace('          off += 4;\n', '').replace('          q++;\n', '')
            .replace('if (*q == c)', 'if (D_800B283C[k] == c)')
            .replace('*(u32 *)((char *)D_800B283C + off)', '*(u32 *)((char *)D_800B283C + (k << 2))'))
    kids = _children(ASSIGN)
    assert kids[0] == want
    assert len(kids) == 3  # both, the cursor alone, the offset alone


def test_a_counter_assigned_between_its_zero_and_the_block_is_left_alone():
    assert _children(ASSIGN.replace('  if (c != 0) {\n', '  k = c;\n  if (c != 0) {\n')) == []


def test_a_cursor_used_elsewhere_keeps_its_cursor():
    kids = _children(ASSIGN.replace('          out[k] = i;', '          out[k] = (u32)q;'))
    assert kids and all('q++;' in kid for kid in kids)


def test_volatile_is_left_alone():
    assert variants(ASSIGN.replace('u32 i;', 'volatile u32 i;'), 'f') == []


def test_it_declares_itself():
    assert any(r.module.endswith('stepped_cursor_index') for r in registry.declared())
