"""A run of zero stores to the stack the target interleaves with its record stores: the local array the original cleared."""
from decomprepair import dead_stack_clear_array as m

ASM = '''glabel f
/* 0 */  addiu      $sp, $sp, -0x30
/* 4 */  sw         $ra, 0x28($sp)
/* 8 */  sw         $zero, 0x14($sp)
/* C */  jal        g
/* 10 */  nop
/* 14 */  addiu      $v0, $zero, 0xFF
/* 18 */  lui        $at, %hi(D_A)
/* 1C */  sb         $v0, %lo(D_A)($at)
/* 20 */  lui        $v0, %hi(D_B)
/* 24 */  lw         $v0, %lo(D_B)($v0)
/* 28 */  sh         $zero, 0x20($sp)
/* 2C */  sw         $zero, 0xC4($v0)
/* 30 */  sh         $zero, 0x22($sp)
/* 34 */  sw         $zero, 0xC8($v0)
/* 38 */  sh         $zero, 0x24($sp)
/* 3C */  sw         $zero, 0xCC($v0)
/* 40 */  lw         $ra, 0x28($sp)
/* 44 */  jr         $ra
/* 48 */  addiu      $sp, $sp, 0x30
endlabel f
'''

SOURCE = '''extern void *D_B;
extern s8 D_A;
void f(void)
{
  volatile unsigned char pad;
  g(1);
  D_A = 0xFF;
  *((s32 *) (((char *) D_B) + 0xC4)) = 0;
  *((s32 *) (((char *) D_B) + 0xC8)) = 0;
  *((s32 *) (((char *) D_B) + 0xCC)) = 0;
}
'''


def test_clears_alternate_with_the_stores_after_the_last_call():
    op, run = m.clears(ASM)
    assert op == 'sh' and [(off, nxt) for _, off, nxt in run] == [(0x20, 1), (0x22, 2), (0x24, 3)]


def test_array_replaces_the_scaffold_and_interleaves():
    (family, out), (block, grouped) = m.variants(SOURCE, 'f', ASM)
    assert family == 'dead_stack_clear_array' and block == 'dead_stack_clear_block'
    assert 'volatile' not in out and '  s16 sp[3];\n' in out
    assert ('  sp[0] = 0;\n  *((s32 *) (((char *) D_B) + 0xC4)) = 0;\n  sp[1] = 0;\n  *((s32 *) (((char *) D_B) + 0xC8)) = 0;\n'
            '  sp[2] = 0;\n  *((s32 *) (((char *) D_B) + 0xCC)) = 0;') in out
    assert '  sp[0] = 0;\n  sp[1] = 0;\n  sp[2] = 0;\n  *((s32 *) (((char *) D_B) + 0xC4))' in grouped


def test_without_a_scaffold_the_array_follows_the_declarations():
    out = m.variants(SOURCE.replace('  volatile unsigned char pad;\n', '  s32 x;\n'), 'f', ASM)[0][1]
    assert '  s32 x;\n  s16 sp[3];\n' in out


def test_leaves_argument_stores_single_stores_and_taken_names():
    assert not m.variants(SOURCE, 'f', ASM.replace('sh         $zero, 0x24($sp)', 'nop').replace('sh         $zero, 0x22($sp)', 'nop'))
    assert not m.variants(SOURCE, 'f', ASM.replace('0x22($sp)', '0x30($sp)'))
    assert not m.variants(SOURCE.replace('pad', 'sp'), 'f', ASM)
    assert not m.variants(SOURCE, 'f', ASM.replace('jal        g', 'nop').replace('0x20($sp)', '0x14($sp)'))
    assert not m.variants(SOURCE, 'f', '')
