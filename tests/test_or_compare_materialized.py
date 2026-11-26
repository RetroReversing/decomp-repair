from decomprepair import or_compare_materialized as repair

SOURCE = """void f(unsigned short *flags, unsigned int count)
{
  if (flags[0] == 1 && (((flags[1] >> 3) & 1) | (count >= 7U)) == 0)
  {
    g();
  }
}
"""


def test_a_comparison_beside_an_or_is_stored():
    [(family, out)] = repair.variants(SOURCE, 'f')
    assert family == 'or_compare_materialized'
    assert '| (truth = (count >= 7U))) == 0)' in out
    assert '{\n    int truth;\n' in out
    assert 'flags[0] == 1 &&' in out


def test_each_side_and_both():
    both = SOURCE.replace('((flags[1] >> 3) & 1)', '(flags[1] != 2)')
    outs = [out for _, out in repair.variants(both, 'f')]
    assert len(outs) == 3
    assert '((truth = (flags[1] != 2)) | (truth2 = (count >= 7U)))' in outs[2]


def test_logical_or_and_shifts_are_not_sites():
    assert repair.variants("void f(int a, int b) { if ((a > 1) || (b < 2)) g(); }", 'f') == []
    assert repair.variants("void f(int a, int b) { if ((a >> 1) | (b << 2)) g(); }", 'f') == []
