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
