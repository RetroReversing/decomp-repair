from decomprepair.loaded_pointee_width import variants

ASM = """
lui        $v0, %hi(D_80000050)
addu       $v0, $v0, $v1
lw         $v0, %lo(D_80000050)($v0)
lbu        $v0, 0x0($v0)
bnez       $v0, .L80000100
nop
"""

SOURCE = """void f(s32 i) {
    if ((*((s32 *) (*((s32 *) (D_80000050 + i))))) == 0) {
        g(i * *((s32 *) D_80000060));
    }
}
"""


def test_a_word_read_of_a_loaded_pointer_takes_the_targets_width():
    children = [text for _, text in variants(SOURCE, 'f', ASM)]
    assert SOURCE.replace('(*((s32 *) (*((s32 *)', '(*((u8 *) (*((s32 *)') in children
    assert len(children) == 1


def test_the_short_spelling_is_read_too():
    source = 'void f(void) { if (*(s32 *)(*(s32 *)&D_0) == 0) g(); }\n'
    assert variants(source, 'f', ASM)[0][1] == source.replace('*(s32 *)(', '*(u8 *)(')


def test_no_narrow_read_through_a_loaded_pointer_means_no_child():
    asm = ASM.replace('lbu        $v0, 0x0($v0)', 'lbu        $v0, 0x4($v0)')
    assert variants(SOURCE, 'f', asm) == []
    assert variants(SOURCE, 'f', 'lw $v0, 0($a0)\naddiu $v0, $a1, 1\nlbu $v1, 0($v0)\n') == []
