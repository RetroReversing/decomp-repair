"""A do-while's bound read through a pointer named at the top of its guard."""
from decomprepair.loop_bound_pointer_local import FAMILY, variants

# A canonical-code builder's length pass (KMC GCC 2.7.2, N64): the histogram slot is the guard and the inner bound.
PASS = '''void f(u32 *H, u32 *out)
{
  u32 c;
  u32 i;
  u32 k;
  k = 0;
  for (c = 1; c < 16; c++) {
    i = 1;
    if (H[c] != 0) {
      out = D_800B283C + k;
      do {
        *out++ = c;
        i++;
        k++;
      } while (H[c] >= i);
    }
  }
}
'''


def _children(text, header=''):
    return [src for fam, src in variants(text, 'f', header) if fam == FAMILY]


def test_the_bound_is_named_first_in_the_guard():
    want = PASS.replace('    if (H[c] != 0) {\n', '    if (H[c] != 0) {\n      u32 *lim = H + c;\n').replace(
        'while (H[c] >= i)', 'while (*lim >= i)')
    assert _children(PASS) == [want]


def test_a_global_tables_element_type_comes_from_its_declaration():
    text = 'extern u16 T[];\n' + PASS.replace('H[c]', 'T[c]')
    kids = _children(text)
    assert len(kids) == 1 and 'u16 *lim = T + c;' in kids[0]


def test_an_index_the_loop_changes_is_left_alone():
    assert _children(PASS.replace('        k++;\n', '        k++;\n        c++;\n')) == []


def test_a_block_that_already_names_lim_is_left_alone():
    assert _children(PASS.replace('      out = D_800B283C + k;', '      u32 *lim = out;\n      out = lim + k;')) == []
