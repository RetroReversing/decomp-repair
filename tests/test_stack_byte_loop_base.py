import pytest

from decomprepair.stack_byte_loop_base import FAMILY, variants

SOURCE = """void copy(signed char *input, u8 seed) {
    u8 bytes[16];
    u8 *prev;
    u8 old, next;
    signed char *read;
    int i;
    i = 0;
    bytes[0] = seed;
    if (seed != 0) {
        read = input;
        do {
            prev = &(bytes)[i];
            old = *prev;
            read += 1;
            i += 1;
            *prev = old - 1;
            next = *read;
            (bytes)[i] = next;
        } while (next != 0);
    }
}"""
ASM = """addiu $a0, $sp, 0x20
beqz $v1, .Lexit
sb $v1, 0x20($sp)
move $a1, $s0
.Lloop:
addu $v1, $a0, $a2
lbu $v0, 0($v1)
addiu $a1, $a1, 1
addiu $a2, $a2, 1
addiu $v0, $v0, -1
sb $v0, 0($v1)
lbu $v1, 0($a1)
move $v0, $a0
addu $v0, $v0, $a2
bnez $v1, .Lloop
sb $v1, 0($v0)"""


def test_keeps_the_buffer_base_and_index_separate():
    [(family, rewrite)] = variants(SOURCE, 'copy', 'mips', ASM, 'u8 *__repair_byte_buffer;')
    assert family == FAMILY
    assert 'u8 *__repair_byte_buffer_;' in rewrite
    assert '__repair_byte_buffer_ = bytes;\n    bytes[0] = seed;' in rewrite
    assert 'prev = __repair_byte_buffer_ + i;' in rewrite
    assert '__repair_byte_buffer_[i] = next;' in rewrite


@pytest.mark.parametrize('source, asm', [
    (SOURCE.replace('u8 bytes[16];', 'u8 *bytes;'), ASM),
    (SOURCE.replace('*prev = old - 1;', '*prev = old - 2;'), ASM),
    (SOURCE, ASM.replace('move $v0, $a0', 'move $v0, $a3')),
    (SOURCE, ASM.replace('sb $v1, 0($v0)', 'sb $v1, 4($v0)')),
])
def test_skips_different_buffer_shapes(source, asm):
    assert variants(source, 'copy', 'mips', asm) == []
