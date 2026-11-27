"""A caller's parameters passed on as one more trailing argument of a callee called twice."""
from decomprepair import forwarded_trailing_argument, registry

ASM = """glabel cat
  addiu $sp, $sp, -0x90
  sw $s0, 0x80($sp)
  addiu $s0, $sp, 0x10
  addu $a0, $s0, $zero
  sw $s1, 0x84($sp)
  addu $s1, $a2, $zero
  sw $ra, 0x88($sp)
  jal load
  nop
  addiu $a0, $sp, 0x50
  jal load
  addu $a1, $s1, $zero
  lw $ra, 0x88($sp)
  jr $ra
  addiu $sp, $sp, 0x90
"""
SOURCE = """s32 load();
void cat(s32 arg0, s32 arg1, s32 arg2)
{
  char sp10[0x40];
  char sp50[0x40];
  load(sp10);
  load(sp50);
}
"""


def children(source=SOURCE, asm=ASM, header='', callees=''):
    return [text for _, text in forwarded_trailing_argument.variants(source, 'cat', asm, header, callees)]


def test_each_call_gets_the_parameter_its_register_holds():
    (text,) = children()
    assert 'load(sp10, arg1);' in text and 'load(sp50, arg2);' in text


def test_a_written_prototype_gains_the_argument():
    (text,) = children(SOURCE.replace('s32 load();', 's32 load(void *);'))
    assert 's32 load(void *, s32);' in text


def test_no_child_without_a_copy_or_against_a_declaration():
    assert children(asm=ASM.replace('addu $a1, $s1, $zero', 'nop')) == []
    assert children(asm=ASM.replace('addu $a1, $s1, $zero', 'addiu $a1, $zero, 4')) == []
    assert children(header='s32 load(void *);') == []
    assert children(callees='s32 load(s32 *a) { return *a; }') == []
    assert children(SOURCE.replace('load(sp50);', 'load(sp50, 1);')) == []


def test_the_registry_runs_it():
    assert registry.get('forwarded_trailing_argument').archs == ('mips',)
