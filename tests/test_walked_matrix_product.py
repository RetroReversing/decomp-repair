"""m2c's cursor walk over a 4x4 float matrix product written as the indexed loops."""
from decomprepair import registry, walked_matrix_product

WALK = """s32 load();
s32 store();
void cat(s32 arg0, s32 arg1)
{
  char sp10[0x40];
  char sp50[0x40];
  char sp90[0x40];
  char *var_s0;
  char *var_v1;
  f32 *temp_v0;
  s32 var_a0;
  s32 var_a1;
  s32 var_a2;
  var_s0 = sp50;
  var_a2 = 0;
  load(var_s0);
  load(sp90);
  loop_1:
  {
    var_a1 = 0;
    var_v1 = sp90;
    var_a0 = var_a2 * 0x10;
    loop_2:
    {
      temp_v0 = sp10 + var_a0;
      var_a0 += 4;
      var_a1 += 1;
      *temp_v0 = ((((*((f32 *) (((char *) var_s0) + 0))) * (*((f32 *) (((char *) var_v1) + 0)))) + ((*((f32 *) (((char *) var_s0) + 4))) * (*((f32 *) (((char *) var_v1) + 0x10))))) + ((*((f32 *) (((char *) var_s0) + 8))) * (*((f32 *) (((char *) var_v1) + 0x20))))) + ((*((f32 *) (((char *) var_v1) + 0x30))) * (*((f32 *) (((char *) var_s0) + 0xC))));
 do { var_v1 += 4; } while (0);
    }
    if (var_a1 < 4)
    {
      goto loop_2;
    }
    var_s0 += 0x10;
    var_a2 += 1;
  }
  if (var_a2 < 4)
  {
    goto loop_1;
  }
  store(sp10, arg0);
}
"""

SDK_ORDER = ('sp10[i][j] = sp50[i][0] * sp90[0][j] + sp50[i][1] * sp90[1][j] + sp50[i][2] * sp90[2][j] '
             '+ sp50[i][3] * sp90[3][j];')


def children(source):
    return [text for _, text in walked_matrix_product.variants(source, 'cat')]


def test_the_walk_becomes_indexed_loops_over_float_matrices():
    first, as_written, columns = children(WALK)
    assert SDK_ORDER in first
    assert 'f32 sp50[4][4];' in first and 'load(sp50);' in first and 'store(sp10, arg0);' in first
    assert 'goto' not in first and 'var_' not in first and 'temp_v0' not in first
    assert first.count('for (') == 2 and 's32 i;' in first and 's32 j;' in first
    assert '+ sp90[3][j] * sp50[i][3];' in as_written
    assert 'sp90[0][j] * sp50[i][0]' in columns


def test_a_walk_that_does_something_else_is_left_alone():
    assert children(WALK.replace('var_a2 += 1;', 'var_a2 += 1; store(sp10, 0);')) == []
    assert children(WALK.replace('var_s0 += 0x10;', 'var_s0 += 0x20;')) == []
    assert children(WALK.replace('if (var_a1 < 4)', 'if (var_a1 < 3)')) == []
    assert children(WALK.replace('(char *) var_v1) + 0x10', '(char *) var_v1) + 0x14')) == []
    assert children(WALK.replace('store(sp10, arg0);', 'store(sp10, var_a2);')) == []
    assert children(WALK.replace('var_a0 = var_a2 * 0x10;', 'var_a0 = var_a2 * 8;')) == []


def test_the_registry_runs_it():
    assert registry.get('walked_matrix_product').families == ('walked_matrix_product',)
