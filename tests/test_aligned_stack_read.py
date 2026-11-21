import pytest

from decomprepair import aligned_stack_read as repair

ASM = '''
addiu $sp, $sp, -72
sw $s3, 60($sp)
move $s3, $a0
sw $s2, 56($sp)
addiu $s2, $sp, 39
srl $s2, $s2, 4
sll $s2, $s2, 4
move $a1, $s2
sw $ra, 64($sp)
jal fetch
addiu $a2, $zero, 4
move $a0, $zero
lhu $s2, 2($s2)
jal allocate
sw $s2, 16($sp)
move $a0, $s3
move $a1, $v0
jal fetch
move $a2, $s2
'''
DRAFT = '''
void load(s32 handle) {
    M2C_UNK stack_slot;
    s32 input;
    s32 size;
    s32 dest;

    input = ((u32) &stack_slot >> 4) * 0x10;
    fetch(input, 4);
    size = M2C_FIELD(input, u16 *, 2) * 8 + 4;
    dest = allocate(size);
    fetch(handle, dest, size);
}
'''


@pytest.mark.parametrize('source', [
    DRAFT,
    DRAFT.replace('M2C_UNK stack_slot;', 's32 stack_slot;').replace('fetch(input, 4);', 'fetch(handle, input, 4);'),
])
def test_recover_buffer_alignment_and_live_incoming_argument(source):
    assert repair.applies(ASM)
    rewritten = repair.rewrite(source, 'load', ASM)
    assert 'u8 stack_slot[32];' in rewritten
    assert '(((u32) &stack_slot + 0xF) >> 4) * 0x10;' in rewritten
    assert rewritten.count('fetch(handle, input, 4);') == 1
    assert 'fetch(handle, dest, size);' in rewritten


@pytest.mark.parametrize('asm', [
    ASM.replace('sll $s2, $s2, 4', 'sll $s2, $s2, 5'),
    ASM.replace('lhu $s2, 2($s2)', 'lhu $s2, 4($s2)'),
    ASM.replace('sw $s2, 56($sp)', 'sw $s2, 24($sp)'),
    ASM.replace('move $a0, $s3', 'move $a0, $zero'),
])
def test_requires_matching_alignment_buffer_read_and_original_input(asm):
    assert repair.rewrite(DRAFT, 'load', asm) is None


@pytest.mark.parametrize('source', [
    DRAFT.replace('fetch(input, 4);', 'fetch(4, input, 4);'),
    DRAFT.replace('fetch(handle, dest, size);', 'fetch(other, dest, size);'),
    DRAFT.replace('    input = ', '    handle = 0;\n    input = '),
])
def test_leaves_incompatible_call_and_source_shapes_alone(source):
    assert repair.rewrite(source, 'load', ASM) is None
