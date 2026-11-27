"""The three steps an m2c table-insertion draft needed: a countdown's masked copy, a parameter that only seeds a local,
and a result local set in both arms of the closing `if`."""
from decomprepair import asm_symbol_read_width, masked_copy_counter_merge, stray_parameter_seed, tail_return_inline

DRAFT = '''s32 f(s32 arg0, s32 arg1)
{
  s32 temp_a2;
  s32 temp_v0;
  s32 var_a1;
  s32 var_s0;
  u16 var_s1;

  var_a1 = arg1;
  var_s0 = 0x63;
  for (var_s1 = 0; var_s1 < 0xA; var_s1++)
  {
    if (t[var_s1] < g)
    {
      var_s0 = 9;
      if (var_s1 < 9U)
      {
        var_a1 = 9 & 0xFFFF;
        do
        {
          temp_a2 = var_a1 * 4;
          var_s0 -= 1;
          t[var_a1] = t[var_a1 - 1];
          h(temp_a2);
          var_a1 = var_s0 & 0xFFFF;
        }
        while (var_s1 < ((u32) (var_s0 & 0xFFFF)));
      }
      var_a1 = var_s1;
      var_s1 = 0xB;
    }
  }

  if (((u32) (var_s0 & 0xFFFF)) >= 0xAU)
  {
    temp_v0 = 0;
  }
  else
  {
    temp_a2 = var_a1 + 1; temp_v0 = temp_a2 & 0xFF;
  }
  return temp_v0;
}
'''


def only(module, source, family):
    return [text for found, text in module.variants(source, 'f') if found == family]


def test_countdown_copy_becomes_the_counter_and_the_step_moves_to_the_loop_end():
    [child] = only(masked_copy_counter_merge, DRAFT, 'countdown_copy_merge')
    loop = child[child.index('do'):child.index('while (var_s1 <')]
    assert loop.index('t[var_s0] = t[var_s0 - 1];') < loop.index('h(temp_a2);') < loop.index('var_s0 -= 1;')
    assert 'temp_a2 = var_s0 * 4;' in loop and 'var_a1' not in loop
    assert 'u16 var_s0;' in child and '& 0xFFFF' not in child
    assert 'var_a1 = var_s1;' in child and 'var_a1 + 1' in child


def test_countdown_is_not_offered_when_the_copy_is_read_after_the_loop():
    source = DRAFT.replace('      var_a1 = var_s1;\n', '      h(var_a1);\n')
    assert not only(masked_copy_counter_merge, source, 'countdown_copy_merge')


def test_a_parameter_that_only_seeds_a_local_goes():
    children = only(stray_parameter_seed, DRAFT, 'stray_parameter_seed_drop')
    assert len(children) == 3
    assert children[0].startswith('s32 f(void)') and 'u8 var_a1;' in children[0] and 'arg1' not in children[0]
    assert 'u16 var_a1;' in children[1] and 's32 var_a1;' in children[2]


def test_a_parameter_that_is_used_stays():
    assert not only(stray_parameter_seed, DRAFT.replace('h(temp_a2);', 'h(arg0 + arg1);'), 'stray_parameter_seed_drop')


def test_the_closing_if_returns_from_each_arm_in_both_orders():
    first, second = only(tail_return_inline, DRAFT, 'two_arm_result_return')
    assert 'return (var_a1 + 1) & 0xFF;\n    }\n    return 0;' in first
    assert '>=' not in first.split('var_s1 = 0xB;')[1]
    assert 'return 0;\n    }\n    return (var_a1 + 1) & 0xFF;' in second


def test_a_base_local_of_a_byte_declared_word_table_is_read_as_words():
    source = '''extern char D_80000000[];
void f(s32 i)
{
  char *base;
  base = D_80000000;
  *((i * 4) + base) = *(((i - 1) * 4) + base);
}
'''
    asm = '''lui $v0, %hi(D_80000000)
addiu $s3, $v0, %lo(D_80000000)
addu $v0, $v0, $s3
lw $v1, 0x0($v0)
'''
    children = [text for family, text in asm_symbol_read_width.variants(source, 'f', asm)
                if family == 'asm_byte_table_deref_width']
    assert any('*(s32 *)((i * 4) + base) = *(s32 *)(((i - 1) * 4) + base);' in child for child in children)
    moved = source.replace('base = D_80000000;', 'base = D_80000000;\n  base += 4;')
    assert not [f for f, _ in asm_symbol_read_width.variants(moved, 'f', asm) if f == 'asm_byte_table_deref_width']
