"""An array element's compound update staged through a temporary, its store after the next counter step."""
from decomprepair.rmw_store_past_step import FAMILY, variants

# A bit-stream decoder's code-length histogram (KMC GCC 2.7.2, N64): three local quantities in the loop's block.
LOOP = '''extern u32 D_80112EE0[];
void f(u32 *q, u32 n, u32 len)
{
  u32 *H;
  u32 i;
  H = D_80112EE0;
  i = 0;
  do {
    *q = len;
    H[len] += 1;
    i++;
    q++;
  } while (i < n);
}
'''


def _children(text):
    return [src for fam, src in variants(text, 'f') if fam == FAMILY]


def test_the_store_moves_past_the_counter_step():
    children = _children(LOOP)
    assert LOOP.replace('    H[len] += 1;\n    i++;\n', '    { u32 hv = H[len] + 1; i++; H[len] = hv; }\n') in children
    assert LOOP.replace('    H[len] += 1;\n    i++;\n', '    { u32 hv = H[len]; i++; H[len] = hv + 1; }\n') in children
    assert LOOP.replace('    H[len] += 1;\n    i++;\n    q++;\n', '    { u32 hv = H[len] + 1; i++; q++; H[len] = hv; }\n') in children


def test_a_step_on_the_index_is_left_alone():
    assert not _children(LOOP.replace('    i++;\n    q++;\n', '    len++;\n'))


def test_an_undeclared_element_type_is_left_alone():
    text = LOOP.replace('  u32 *H;\n', '').replace('  H = D_80112EE0;\n', '').replace('H[len]', 'G[len]')
    assert not _children(text)


def test_a_compound_operand_is_parenthesised():
    text = LOOP.replace('H[len] += 1;', 'H[len] += len | 1;')
    assert any('hv = H[len] + (len | 1);' in src for src in _children(text))
