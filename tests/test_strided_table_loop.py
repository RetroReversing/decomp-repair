import pytest

from decomprepair import strided_table_loop as loop

STEPS = '''addiu $s4, $s4, 8
addiu $s1, $s1, 2
addiu $s5, $s5, 1
'''


def run(family, source, asm='', name='f'):
    return getattr(loop, family)(source, name, 'mips', asm)


HALF_SOURCE = '''extern s16 D_80100004;
extern s16 D_80100006;
void f(void)
{
  s32 off;
  s32 i;
  off = 0;
  i = 0;
  do
  {
    *((&D_80100004) + off) = 1;
    *((&D_80100006) + off) = 2;
    off += 8;
    i++;
  }
  while (i < 4);
}
'''
HALF_ASM = '''/* 0 80000000 3C018010 */  lui        $at, %hi(D_80100004)
/* 4 80000004 00340821 */  addu       $at, $at, $s4
/* 8 80000008 A4220004 */  sh         $v0, %lo(D_80100004)($at)
/* c 8000000c 3C018010 */  lui        $at, %hi(D_80100006)
/* 10 80000010 00340821 */  addu       $at, $at, $s4
/* 14 80000014 A4220006 */  sh         $v0, %lo(D_80100006)($at)
/* 18 80000018 26940008 */  addiu      $s4, $s4, 0x8
'''


def test_byte_offset_where_the_target_adds_the_counter_unscaled():
    [(family, child)] = run('byte_offset_variants', HALF_SOURCE, HALF_ASM)
    assert family == loop.OFFSET
    assert '*(((s16 *) (((s8 *) (&D_80100004)) + off))) = 1;' in child
    assert '*(((s16 *) (((s8 *) (&D_80100006)) + off))) = 2;' in child


def test_byte_offset_needs_the_unshifted_addition_and_the_same_step():
    assert not run('byte_offset_variants', HALF_SOURCE, HALF_ASM.replace('addu       $at, $at, $s4', 'sll $at, $at, 1'))
    assert not run('byte_offset_variants', HALF_SOURCE, HALF_ASM.replace('0x8', '0x10'))
    assert not run('byte_offset_variants', HALF_SOURCE.replace('extern s16 D_80100004;', 'extern u8 D_80100004;'),
                   HALF_ASM.replace('D_80100006', 'D_80100008'))


def test_byte_offset_reads_a_helper_that_adds_the_counter_to_the_symbol():
    source = HALF_SOURCE.replace('void f', 'inline static s16 *at(long arg0)\n{\n  return (&D_80100004) + arg0;\n}\n\nvoid f')
    source = source.replace('*((&D_80100004) + off) = 1;', '*at(off) = 1;')
    [(_, child)] = run('byte_offset_variants', source, HALF_ASM)
    assert '*((s16 *) (((s8 *) (&D_80100004)) + off)) = 1;' in child


def test_byte_offset_reads_the_address_built_once_and_added_to_the_counter():
    asm = '''lui $s7, %hi(D_80100004)
addiu $s7, $s7, %lo(D_80100004)
addu $v0, $s4, $s7
lhu $v0, 0($v0)
addiu $s4, $s4, 8
'''
    [(_, child)] = run('byte_offset_variants', HALF_SOURCE.replace('*((&D_80100004) + off) = 1;', 'x = *(off + (&D_80100004));'), asm)
    assert 'x = *(((s16 *) (((s8 *) (&D_80100004)) + off)));' in child


RECORD_ASM = HALF_ASM + '''lhu $v0, %lo(D_80100006)($v1)
'''


def test_record_fields_for_neighbouring_symbols_in_every_subset():
    [(_, offset)] = run('byte_offset_variants', HALF_SOURCE, HALF_ASM)
    children = run('record_field_variants', offset, HALF_ASM)
    assert children and all(family == loop.FIELDS for family, _ in children)
    first = children[0][1]
    assert 'typedef struct { s16 f0; s16 f2; } DecompRecord80100004;' in first
    assert '(((DecompRecord80100004 *) (((s8 *) (&D_80100004)) + off))->f0) = 1;' in first
    assert '(((DecompRecord80100004 *) (((s8 *) (&D_80100004)) + off))->f2) = 2;' in first


def test_record_fields_need_neighbours_the_target_addresses():
    [(_, offset)] = run('byte_offset_variants', HALF_SOURCE, HALF_ASM)
    assert not run('record_field_variants', offset, HALF_ASM.replace('D_80100006', 'D_80100106'))
    assert not run('record_field_variants', offset, 'nop')


def test_record_fields_read_a_byte_table_and_start_at_a_declared_neighbour():
    source = '''extern u16 D_80100000;
extern u8 D_80100002[];
extern u8 D_80100003[];
void f(void)
{
  s32 off;
  s32 i;
  off = 0;
  i = 0;
  do
  {
    x = *(D_80100002 + off);
    y = *(D_80100003 + off);
    off += 6;
    i++;
  }
  while (i < 4);
}
'''
    asm = '''lbu $v0, %lo(D_80100002)($v0)
lbu $v0, %lo(D_80100003)($v0)
'''
    children = run('record_field_variants', source, asm)
    assert children
    child = children[0][1]
    assert 'typedef struct { u8 f0; u8 f1; } DecompRecord80100002;' in child
    assert 'x = (((DecompRecord80100002 *) (((s8 *) (&D_80100002)) + off))->f0);' in child
    assert any('typedef struct { u8 pad0[2]; u8 f2; u8 f3; } DecompRecord80100000;' in c for _, c in children)


JOIN_SOURCE = '''void f(void)
{
  s32 i;
  u16 *p;
  i = 0;
  p = &table;
  do
  {
    if (a != 0)
    {
      if (b == 0)
      {
        if (c & 2)
        {
          first(i);
          p += 4;
        }
        else
        {
          goto block_9;
        }
      }
      else
      {
        do
        {
          if (d)
          {
            second(i);
            goto block_9;
          }
        }
        while (0);
        e = 1;
        p += 4;
      }
    }
    else
    {
      block_9:
      p += 4;
    }
    i++;
  }
  while (i < 4);
}
'''


def test_join_increment_writes_the_step_once_and_drops_the_gotos():
    [(family, child)] = run('join_increment_variants', JOIN_SOURCE)
    assert family == loop.JOIN
    assert 'goto' not in child and 'block_9' not in child
    assert child.count('p += 4;') == 1
    assert child.index('p += 4;') > child.index('second(i);') and child.index('p += 4;') < child.index('i++;')
    # the guard that jumped out of the do-while(0) now has the rest as its other arm
    assert 'if (d)' in child and 'else' in child
    assert child.index('e = 1;') > child.index('second(i);')


def test_join_increment_keeps_a_function_whose_paths_do_not_all_step():
    assert not run('join_increment_variants', JOIN_SOURCE.replace('p += 4;\n        }\n        else\n        {\n          goto block_9;',
                                                                 'p += 4;\n        }\n        else\n        {\n          other();'))
    assert not run('join_increment_variants', JOIN_SOURCE.replace('goto block_9;\n          }', 'k = 1;\n          }'))
    assert not run('join_increment_variants', JOIN_SOURCE.replace('while (i < 4)', 'while (0)'))


def test_sign_test_of_a_halfword_where_the_target_shifts_and_branches_on_sign():
    source = 'void f(void)\n{\n  s32 t;\n  if (t & 0x8000)\n  {\n    g();\n  }\n}\n'
    asm = 'sll $v0, $v1, 16\nbgez $v0, .L1\nnop\n'
    [(family, child)] = run('sign_test_variants', source, asm)
    assert family == loop.SIGN_TEST and 'if ((s16) t < 0)' in child
    assert not run('sign_test_variants', source, 'andi $v0, $v1, 0x8000\nbeqz $v0, .L1\n')


def test_repeated_load_written_at_each_use():
    source = 'void f(void)\n{\n  u16 t;\n  t = (u16) (*(p + 1));\n  *q = ((*r) ^ t) & t;\n  t = 5;\n}\n'
    [(family, child)] = run('repeated_load_variants', source)
    assert family == loop.REPEATED_LOAD
    assert '*q = ((*r) ^ ((u16) (*(p + 1)))) & ((u16) (*(p + 1)));' in child
    assert 't = (u16)' not in child
    # a temporary read again afterwards, or one whose address is taken, stays
    assert not run('repeated_load_variants', source.replace('t = 5;', 'z = t;'))
    assert not run('repeated_load_variants', source.replace('& t;', '& t; h(&t);'))


BASE_SOURCE = '''extern u16 D_80100010;
void f(void)
{
  s32 i;
  s32 off;
  i = 0;
  off = 0;
  do
  {
    a = *((u16 *) (((s8 *) (&D_80100010)) + off));
    b = *((u16 *) (((s8 *) (&D_80100010)) + off));
    off += 2;
    i++;
  }
  while (i < 4);
}
'''
BASE_ASM = '''lui $s7, %hi(D_80100010)
addiu $s7, $s7, %lo(D_80100010)
.L1:
addu $v0, $s1, $s7
lhu $v0, 0($v0)
addiu $s1, $s1, 2
'''


def test_loop_base_pointer_before_the_loop_added_the_way_the_target_adds_it():
    [(family, child)] = run('loop_base_pointer_variants', BASE_SOURCE, BASE_ASM)
    assert family == loop.BASE_POINTER
    assert 'u16 *decomp_base_D_80100010;' in child
    assert child.index('decomp_base_D_80100010 = &D_80100010;') < child.index('do')
    assert child.count('(off + (u32) decomp_base_D_80100010)') == 2
    [(_, other)] = run('loop_base_pointer_variants', BASE_SOURCE, BASE_ASM.replace('$s1, $s7', '$s7, $s1'))
    assert '((u32) decomp_base_D_80100010 + off)' in other
    assert not run('loop_base_pointer_variants', BASE_SOURCE, BASE_ASM.replace('lui $s7', 'lui $v1').replace('$s7', '$v1'))


ORDER_SOURCE = '''void f(void)
{
  s32 a;
  s32 b;
  s32 i;
  u16 *p;
  u16 *q;
  call(&other);
  p = &D_80100020;
  a = 0;
  q = &other;
  b = 0;
  i = 0;
  do
  {
    a += 8;
    b += 2;
    i++;
  }
  while (i < 4);
}
'''
ORDER_ASM = '''jal call
nop
addu $s5, $zero, $zero
lui $s6, %hi(D_80100020)
addiu $s6, $s6, %lo(D_80100020)
addu $s4, $zero, $zero
addu $s2, $s0, $zero
addu $s1, $zero, $zero
.L1:
lw $v0, 0($s6)
addiu $s4, $s4, 8
addiu $s1, $s1, 2
addiu $s5, $s5, 1
slti $v0, $s5, 4
bnez $v0, .L1
nop
'''


def test_loop_init_order_follows_the_registers_the_target_initializes():
    [(family, child)] = run('loop_init_order_variants', ORDER_SOURCE, ORDER_ASM)
    assert family == loop.INIT_ORDER
    order = [line.strip() for line in child.split('do')[0].split('\n') if '=' in line and 'call' not in line]
    assert order == ['i = 0;', 'p = &D_80100020;', 'a = 0;', 'q = &other;', 'b = 0;']
    assert not run('loop_init_order_variants', ORDER_SOURCE, ORDER_ASM.replace('addu $s1, $zero, $zero\n', ''))


def test_narrow_symbol_to_the_width_the_target_uses():
    source = '''extern s32 D_80100030;
extern s32 D_80100034;
void f(void)
{
  a = *((s32 *) (((s8 *) (&D_80100030)) + off));
  b = D_80100034;
}
'''
    asm = '''lui $v0, %hi(D_80100030)
addu $v0, $v0, $s1
lhu $v0, %lo(D_80100030)($v0)
lui $v1, %hi(D_80100034)
lw $v1, %lo(D_80100034)($v1)
'''
    [(family, child)] = run('narrow_symbol_variants', source, asm)
    assert family == loop.NARROW
    assert 'extern u16 D_80100030;' in child and 'a = *((u16 *) (((s8 *) (&D_80100030)) + off));' in child
    assert 'extern s32 D_80100034;' in child
    assert not run('narrow_symbol_variants', source, asm.replace('lhu', 'lw'))


def test_call_result_stored_directly_when_the_name_is_a_counter():
    source = '''extern s32 result;
void f(void)
{
  s32 i;
  do
  {
    i += 2;
  }
  while (i < 4);
  switch (x)
  {
    case 1:
      i = first(1);
      result = i;
      break;
    case 2:
      i = second(2);
      result = i;
      break;
  }
}
'''
    [(family, child)] = run('call_result_direct_variants', source)
    assert family == loop.RESULT_DIRECT
    assert 'result = first(1);' in child and 'result = second(2);' in child and 'i = first' not in child
    assert not run('call_result_direct_variants', source.replace('i += 2;', 'k += 2;'))
    assert not run('call_result_direct_variants', source.replace('break;\n  }', 'break;\n  }\n  use(i);'))


PROBE_ASM = HALF_ASM + HALF_ASM


def test_probe_joins_the_profile_without_strength_reduction_with_the_spellings():
    fn = {'best_source': HALF_SOURCE, 'name': 'f', 'asm': PROBE_ASM}
    own = {'toolchain': 'gcc-2.7.2-kmc', 'flags': ['-G0', '-mips3', '-mgp32', '-mfp32', '-O2']}
    found = loop.probes({'arch': 'mips'}, fn, own)
    assert found and all(flags == [*own['flags'], '-fno-strength-reduce'] for flags, _ in found)
    assert 'DecompRecord80100004' in found[-1][1] and 'DecompRecord80100004' not in found[0][1]
    assert not loop.probes({'arch': 'mips'}, fn, {**own, 'flags': [*own['flags'], '-fno-strength-reduce']})
    assert not loop.probes({'arch': 'mips'}, fn, {**own, 'toolchain': 'gcc-2.8.1-pm'})
    assert not loop.probes({'arch': 'mips'}, {**fn, 'asm': 'nop'}, own)


@pytest.mark.parametrize('family', ['byte_offset_variants', 'record_field_variants', 'join_increment_variants',
                                    'sign_test_variants', 'repeated_load_variants', 'loop_base_pointer_variants',
                                    'loop_init_order_variants', 'narrow_symbol_variants', 'call_result_direct_variants'])
def test_every_family_leaves_other_architectures_and_missing_functions_alone(family):
    assert not getattr(loop, family)(HALF_SOURCE, 'f', 'arm', HALF_ASM)
    assert not getattr(loop, family)(HALF_SOURCE, 'missing', 'mips', HALF_ASM)
