from decomprepair import compare_tree_arm_order as module

ASM = '''
glabel run
lui   $v0, %hi(D_80000000)
lhu   $v1, %lo(D_80000000)($v0)
addiu $v0, $zero, 0x3
beq   $v1, $v0, .Lthree
slti  $v0, $v1, 0x4
beqz  $v0, .Lhigh
addiu $v0, $zero, 0x1
beq   $v1, $v0, .Lone
nop
j     .Lend
nop
.Lhigh:
addiu $v0, $zero, 0x8
beq   $v1, $v0, .Leight
addiu $v0, $zero, 0x20
bne   $v1, $v0, .Lend
nop
jal   f0
nop
j     .Lend
nop
.Lone:
jal   f1
nop
j     .Lend
nop
.Leight:
jal   f8
nop
j     .Lend
nop
.Lthree:
jal   f3
nop
.Lend:
jr    $ra
nop
endlabel run
'''

SOURCE = '''void run(void)
{
  switch (D_80000000)
  {
    case 1:
      f1();
      break;
    case 3:
      f3();
      break;
    case 8:
      f8();
      break;
    case 0x20:
      f0();
      break;
    case 0:
      break;
  }
}
'''


def test_arms_follow_the_target_blocks():
    (family, text), = module.variants(SOURCE, 'run', asm=ASM)
    assert family == module.FAMILY
    order = [text.index(call) for call in ('f0();', 'f1();', 'f8();', 'f3();')]
    assert order == sorted(order)
    assert text.count('case') == SOURCE.count('case')


def test_nothing_without_the_target_or_when_the_order_agrees():
    assert module.variants(SOURCE, 'run') == []
    (_, text), = module.variants(SOURCE, 'run', asm=ASM)
    assert module.variants(text, 'run', asm=ASM) == []


def test_arm_that_falls_through_moves_with_its_group():
    source = SOURCE.replace('      f1();\n      break;\n', '      f1();\n')
    for _, text in module.variants(source, 'run', asm=ASM):
        assert text.index('f1();') < text.index('f3();') < text.index('case 8:')
