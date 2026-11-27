from decomprepair.subscript_load_stage import FAMILY, variants

SOURCE = '''extern s8 T[4][8][34];
void use(s32, s32);

void f(void)
{
  u8 out[8];
  s32 i;
  s32 j;
  s32 k;

  for (i = 0; i < 4; i++) {
    for (j = 0; j < 8; j++) {
      out[j] = T[i][j][T[i][j][0] + 2];
    }
    use(i, 1);
    for (j = 0; j < 8; j++) {
      for (k = 0; k < T[i][j][1]; k++) {
        if (T[i][j][k + 2] == out[j]) { T[i][j][0] = k; break; }
      }
    }
  }
}
'''


def test_the_selector_load_goes_through_the_counter_a_later_loop_uses():
    children = variants(SOURCE, 'f')
    assert [family for family, _ in children] == [FAMILY]
    assert '      k = T[i][j][0];\n      out[j] = T[i][j][k + 2];\n' in children[0][1]


def test_a_new_local_when_none_is_free():
    source = SOURCE.replace('  s32 k;\n', '').replace('k = 0; k <', 'i = 0; i <')
    (_, child), = variants(source, 'f')
    assert 's32 __repair_index;' in child
    assert '__repair_index = T[i][j][0];' in child


def test_nothing_without_a_load_inside_a_subscript():
    assert variants('void f(void)\n{\n  s32 i;\n  i = 0;\n  a[i + 1] = b[i];\n}\n', 'f') == []
