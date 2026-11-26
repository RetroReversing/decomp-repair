"""`t = G; G = t + 1;` written as `t = G++;`."""
from decomprepair import postinc_copy_merge as m

SOURCE = '''s32 f(void *arg0)
{
  s32 temp_v1;
  s32 n;
  g(arg0);
  temp_v1 = D_8017B220;
  D_8017B220 = temp_v1 + 1;
  h(temp_v1);
  n = D_80100000;
  D_80100000 = n - 1;
  return temp_v1 + n;
}
'''


def test_old_value_local_written_as_postincrement():
    # An SN GCC 2.7.2 audio sequence starter: 415 -> 50 with `temp_v1 = D_8017B220++;` (the target copies the old
    # value into a saved register after the store).
    (family, both), (_, first), (_, second) = m.variants(SOURCE, 'f')
    assert family == 'postinc_copy_merge'
    assert 'temp_v1 = D_8017B220++;\n  h(temp_v1);' in both and 'n = D_80100000--;\n  return' in both
    assert 'temp_v1 = D_8017B220++;' in first and 'D_80100000 = n - 1;' in first
    assert 'D_8017B220 = temp_v1 + 1;' in second and 'n = D_80100000--;' in second
    (_, one), = m.variants(SOURCE.replace('temp_v1 + 1;', '1 + temp_v1;').replace('n - 1', 'n * 2'), 'f')
    assert 'temp_v1 = D_8017B220++;' in one


def test_left_alone_otherwise():
    # not adjacent, another step than one, or the same name on both sides
    assert m.variants(SOURCE.replace('  D_8017B220 = temp_v1 + 1;\n', '  k();\n  D_8017B220 = temp_v1 + 1;\n')
                      .replace('n - 1', 'n - 2'), 'f') == []
    assert m.variants(SOURCE.replace('temp_v1 + 1;', 'temp_v1 + 2;').replace('n - 1', 'n - 2'), 'f') == []
    assert m.variants('void f(void)\n{\n  x = x;\n  x = x + 1;\n}\n', 'f') == []
