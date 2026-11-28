"""A call short of the words the target copies from the caller's records to the stack gets them."""
from decomprepair import loaded_stack_arguments as s
from decomprepair import registry

SOURCE = '''int g(void *, int, int, int);
extern int D_0, D_1, D_2;
void f(void *a, void *b, float *c) {
    if (D_0 == 0) {
        g(&D_1, M(a, 0), M(a, 4), M(a, 8));
    } else {
        g(&D_2, M(a, 0), M(a, 4), M(a, 8));
    }
}
'''
# Two arms share one `jal`: the first path's `j` and its delay slot precede the second arm's block.
ASM = '''lui        $v0, %hi(D_0)
lw         $v0, %lo(D_0)($v0)
addiu      $sp, $sp, -0x28
bnez       $v0, .L1
sw         $ra, 0x20($sp)
lwc1       $fv0, 0x0($a2)
swc1       $fv0, 0x10($sp)
lwc1       $fv0, 0x4($a1)
swc1       $fv0, 0x14($sp)
lw         $a1, 0x0($a0)
lw         $a2, 0x4($a0)
lw         $a3, 0x8($a0)
lui        $a0, %hi(D_1)
j          .L2
addiu      $a0, $a0, %lo(D_1)
.L1:
lwc1       $fv0, 0x0($a2)
swc1       $fv0, 0x10($sp)
lwc1       $fv0, 0x4($a1)
swc1       $fv0, 0x14($sp)
lw         $a1, 0x0($a0)
lw         $a2, 0x4($a0)
lw         $a3, 0x8($a0)
lui        $a0, %hi(D_2)
addiu      $a0, $a0, %lo(D_2)
.L2:
jal        g
nop
lw         $ra, 0x20($sp)
'''
ADDED = '*(float *)((char *)c + 0x0), *(float *)((char *)b + 0x4)'


def test_appends_the_stack_words_then_types_the_register_words_float():
    children = [out for _, out in s.variants(SOURCE, 'f', ASM)]
    assert len(children) == 2
    assert f'g(&D_1, M(a, 0), M(a, 4), M(a, 8), {ADDED});' in children[0]
    assert 'int g(void *, int, int, int, float, float);' in children[0]
    registers = ', '.join(f'*(float *)((char *)a + {offset:#x})' for offset in (0, 4, 8))
    for symbol in ('D_1', 'D_2'):
        assert f'g(&{symbol}, {registers}, {ADDED});' in children[1]
    assert 'int g(void *, float, float, float, float, float);' in children[1]


def test_declares_a_callee_the_source_and_header_do_not():
    child = s.variants(SOURCE.replace('int g(void *, int, int, int);\n', ''), 'f', ASM)[0][1]
    assert 'void g(void *, int, int, int, float, float);\nvoid f(' in child
    assert s.variants(SOURCE.replace('int g(void *, int, int, int);\n', ''), 'f', ASM, 'int g();') == []


def test_nothing_when_the_call_is_complete_or_a_register_was_rewritten():
    whole = s.variants(SOURCE, 'f', ASM)[0][1]
    assert s.variants(whole, 'f', ASM) == []
    rewritten = ASM.replace('lwc1       $fv0, 0x0($a2)', 'move       $a2, $zero\nlwc1       $fv0, 0x0($a2)')
    assert s.variants(SOURCE, 'f', rewritten) == []


def test_declared():
    assert s.FAMILY in {family for repair in registry.declared() for family in repair.families}
