import pytest

from decomprepair import loop_storage_shapes as loop
from decomprepair import passthrough_argument_repairs as wrapper

WRAPPER = '''M2C_UNK consume(s32); /* extern */
extern s32 slot;
void relay(void) {
    consume(slot);
}
'''
WRAPPER_ASM = '''lui $a1, %hi(slot)
lw $a1, %lo(slot)($a1)
addiu $sp, $sp, -24
sw $ra, 16($sp)
jal consume
nop
lw $ra, 16($sp)
jr $ra
addiu $sp, $sp, 24
'''
LOOP_ASM = '''move $t2, $a0
lw $v0, 4($t2)
sw $v0, 0($a1)
lw $v0, 12($t2)
move $t0, $zero
sw $v0, 4($a1)
lw $v0, 16($t2)
move $a3, $t2
move $a2, $a1
sw $v0, 8($a1)
.Lcopy:
lw $v0, 24($a3)
addiu $t0, $t0, 1
addiu $a3, $a3, 4
sw $v0, 12($a2)
slti $v0, $t0, 16
bnez $v0, .Lcopy
addiu $a2, $a2, 4
jr $ra
nop
'''
LOOP = '''void records(void *src, void *dst) {
    s32 i;
    s32 word;
    void *input;
    void *output;
    M2C_FIELD(dst, s32 *, 0) = (s32) M2C_FIELD(src, s32 *, 4);
    i = 0;
    M2C_FIELD(dst, s32 *, 4) = (s32) M2C_FIELD(src, s32 *, 12);
    input = src;
    output = dst;
    M2C_FIELD(dst, s32 *, 8) = (s32) M2C_FIELD(src, s32 *, 16);
    do {
        word = M2C_FIELD(input, s32 *, 24);
        i += 1;
        input += 4;
        M2C_FIELD(output, s32 *, 12) = word;
        output += 4;
    } while (i < 16);
}
'''


def test_untouched_first_argument_recovers_generated_caller_and_callee_signatures():
    candidate = wrapper.missing_entry_argument(WRAPPER, 'relay', WRAPPER_ASM)
    assert 'void relay(s32 arg0)' in candidate
    assert 'consume(arg0, slot);' in candidate
    assert 'M2C_UNK consume(s32, s32);' in candidate


def test_wrapper_requires_physical_second_argument_and_owned_prototype():
    assert wrapper.missing_entry_argument(WRAPPER, 'relay', WRAPPER_ASM.replace('$a1', '$a0')) is None
    assert wrapper.missing_entry_argument(WRAPPER, 'relay', WRAPPER_ASM.replace('nop', 'move $a0, $zero')) is None
    assert wrapper.missing_entry_argument(WRAPPER.replace(' /* extern */', ''), 'relay', WRAPPER_ASM) is None
    assert wrapper.missing_entry_argument(WRAPPER, 'relay', WRAPPER_ASM, 'void consume(int);') is None


@pytest.mark.parametrize('source', [
    LOOP,
    LOOP.replace('do {', '__repair_rows: {').replace('} while (i < 16);', '}\n    if (i < 16) goto __repair_rows;'),
])
def test_measured_setup_follows_last_fixed_store_and_keeps_backedge(source):
    candidate = loop.measured_copy_setup(source, 'records', LOOP_ASM)
    assert candidate.index('s32 *, 8)') < candidate.index('input = src;')
    assert 'if (i < 16) goto __repair_rows;' in candidate
    assert 'M2C_FIELD(output, s32 *, 12) = word;' in candidate


def test_measured_copy_setup_requires_matching_offsets_and_latch():
    assert loop.measured_copy_setup(LOOP, 'records', LOOP_ASM.replace('lw $v0, 16', 'lw $v0, 20')) is None
    assert loop.measured_copy_setup(LOOP, 'records', LOOP_ASM.replace('bnez $v0, .Lcopy', 'bnez $v0, .Lother')) is None
    assert loop.measured_copy_setup(LOOP.replace('output += 4;', 'output += 8;'), 'records', LOOP_ASM) is None
