"""A call short of the zero words the target stores on the stack gets them."""
from decomprepair import registry
from decomprepair import stack_argument_tail as s

SOURCE = '''extern s32 g();
void f(s32 a) {
    volatile unsigned int pad;
    g(a, 2, 3, 4, 5, 0);
}
'''
ASM = '''addiu      $sp, $sp, -0x30
sw         $ra, 0x28($sp)
addiu      $v0, $zero, 0x5
sw         $v0, 0x10($sp)
sw         $zero, 0x14($sp)
sw         $zero, 0x18($sp)
addiu      $a1, $zero, 0x2
jal        g
sw         $zero, 0x1C($sp)
lw         $ra, 0x28($sp)
'''


def test_appends_the_zeros_and_drops_an_unused_volatile():
    children = [out for _, out in s.variants(SOURCE, 'f', ASM)]
    assert 'g(a, 2, 3, 4, 5, 0, 0, 0);' in children[0] and 'pad' in children[0]
    assert 'g(a, 2, 3, 4, 5, 0, 0, 0);' in children[1] and 'pad' not in children[1]


def test_nothing_to_add_or_not_a_zero():
    assert s.variants(SOURCE.replace('5, 0)', '5, 0, 0, 0)'), 'f', ASM) == []
    assert s.variants(SOURCE, 'f', ASM.replace('$zero, 0x1C', '$v1, 0x1C')) == []
    assert s.variants(SOURCE, 'f', '') == []


def test_declared_to_the_registry():
    assert any(r.module == 'stack_argument_tail' for r in registry.declared())


def test_prologue_saves_are_not_arguments_and_a_float_zero_is_a_word():
    source = 'extern s32 g();\nvoid f(void) {\n    g(1, 2, 3, 4, 5, (float) 0);\n}\n'
    asm = '''addiu      $sp, $sp, -0x38
sw         $ra, 0x34($sp)
sw         $s0, 0x30($sp)
addiu      $s0, $zero, 0x5
sw         $s0, 0x10($sp)
sw         $zero, 0x14($sp)
sw         $zero, 0x18($sp)
sw         $zero, 0x1C($sp)
jal        g
addu       $a0, $zero, $zero
lw         $ra, 0x34($sp)
lw         $s0, 0x30($sp)
'''
    children = [out for _, out in s.variants(source, 'f', asm)]
    assert 'g(1, 2, 3, 4, 5, 0, 0, 0);' in children[0]


CONSTANT = '''s32 g(s32 *, s32, s32, s32);
void f(s32 *p, s32 c) {
    if (c) {
        g(p, 1, 2, 3);
    } else {
        g(&D_1, 4, 5, 6);
    }
}
'''
CONSTANT_ASM = '''addiu      $sp, $sp, -0x20
sw         $ra, 0x18($sp)
lw         $ra, 0x18($sp)
addiu      $a1, $zero, 0x1
addiu      $v0, $zero, 0x46
jal        g
sw         $v0, 0x10($sp)
addiu      $v0, $zero, 0x46
sw         $v0, 0x10($sp)
jal        g
nop
'''


def test_a_constant_fifth_word_is_appended_and_the_prototype_widened():
    (_, out), = s.variants(CONSTANT, 'f', CONSTANT_ASM)[:1]
    assert 'g(p, 1, 2, 3, 0x46);' in out
    assert 's32 g(s32 *, s32, s32, s32, s32);' in out


def test_a_word_loaded_from_elsewhere_is_not_guessed():
    asm = CONSTANT_ASM.replace('addiu      $v0, $zero, 0x46', 'lw         $v0, 0x20($sp)')
    assert s.variants(CONSTANT, 'f', asm) == []
