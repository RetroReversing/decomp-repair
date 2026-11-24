"""m2c's scratch array for stack slots: sized to the target's frame, rebased above the argument area, typed by access."""
from decomprepair import registry
from decomprepair import scratch_frame_array as s

SOURCE = '''void g(f32 *, s32);
#define sp118 (*(s32 *)(sp + 0x118))
#define sp120 (*(s32 *)(sp + 0x120))
void f(void *arg0) {
    u8 sp[360];
    void *temp_s0;

    temp_s0 = h(arg0);
    g(&sp118, 1);
    k(sp118, sp120);
}
'''
ASM = '''addiu      $sp, $sp, -0x168
sw         $s0, 0x158($sp)
sw         $ra, 0x160($sp)
jal        h
sw         $s1, 0x15c($sp)
addiu      $a0, $sp, 0x118
jal        g
addiu      $a1, $zero, 0x1
lwc1       $f12, 0x118($sp)
lwc1       $f14, 0x120($sp)
jal        k
lw         $ra, 0x160($sp)
addiu      $sp, $sp, 0x168
'''
FULL = SOURCE.replace('360', '328').replace('s32 *)(sp + 0x118', 'f32 *)(sp + 0x108').replace('s32 *)(sp + 0x120', 'f32 *)(sp + 0x110')


def test_size_rebase_and_retype_together_are_the_first_child():
    children = s.variants(SOURCE, 'f', ASM)
    assert children[0] == (s.FAMILY, FULL)


def test_each_part_alone_and_in_pairs():
    texts = [text for _, text in s.variants(SOURCE, 'f', ASM)]
    assert len(texts) == len(set(texts)) == 7
    assert any('u8 sp[328];' in t and 'sp + 0x118' in t and 's32' in t for t in texts)  # the size alone
    assert any('u8 sp[360];' in t and 'sp + 0x108' in t and 's32' in t for t in texts)  # the rebase alone
    assert any('u8 sp[360];' in t and 'f32 *)(sp + 0x118' in t for t in texts)  # the retype alone


def test_a_slot_the_target_moves_as_a_word_stays_an_integer():
    asm = ASM.replace('lwc1       $f14', 'lw         $a1')
    full = s.variants(SOURCE, 'f', asm)[0][1]
    assert '#define sp120 (*(s32 *)(sp + 0x110))' in full and '#define sp118 (*(f32 *)(sp + 0x108))' in full


def test_a_double_slot_is_typed_f64():
    asm = ASM.replace('lwc1       $f14, 0x120', 'ldc1       $f14, 0x120')
    source = SOURCE.replace('s32 *)(sp + 0x120', 's64 *)(sp + 0x120')
    assert '#define sp120 (*(f64 *)(sp + 0x110))' in s.variants(source, 'f', asm)[0][1]


def test_an_array_already_right_has_only_the_other_children():
    texts = [text for _, text in s.variants(FULL.replace('f32 *)(sp + 0x108', 's32 *)(sp + 0x108'), 'f', ASM)]
    assert texts and all('u8 sp[328];' in t for t in texts)


def test_nothing_without_evidence():
    assert not s.variants(SOURCE, 'f', '')
    assert not s.variants(SOURCE, 'f', ASM.replace('0x158($sp)', '0x100($sp)'))  # a saved register below a slot
    assert not s.variants(SOURCE.replace('u8 sp[360];', 'u8 sp[360];\n    u8 sp[8];'), 'f', ASM)
    assert not s.variants(SOURCE.replace('k(sp118', 'k(sp[4]'), 'f', ASM)  # indexed use: another layout


def test_a_leaf_has_no_argument_area_to_rebase():
    asm = 'addiu $sp, $sp, -0x30\nsw $s0, 0x28($sp)\nlwc1 $f0, 0x10($sp)\naddiu $sp, $sp, 0x30\n'
    source = '#define sp10 (*(s32 *)(sp + 0x10))\nf32 f(void) {\n    u8 sp[48];\n\n    return sp10;\n}\n'
    texts = [text for _, text in s.variants(source, 'f', asm)]
    assert texts and all('sp + 0x10' in t for t in texts) and any('u8 sp[40];' in t for t in texts)


def test_it_is_declared():
    assert 'scratch_frame_array' in [r.module for r in registry.declared()]
