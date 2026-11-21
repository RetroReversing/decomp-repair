from decomprepair.scoped_byte_read_call import FAMILY, variants

SOURCE = '''extern u8 options[];
void f(int channel) {
    if (options[0] != 0) {
        send(channel);
        if (options[0] >= 2U) {
            reset(channel);
        }
    }
}'''
ASM = '''lui $s2, %hi(options)
addiu $s2, $s2, %lo(options)
lbu $v0, 0($s2)
beqz $v0, .Lskip
move $a0, $s1
jal send
nop
lbu $v0, 0($s2)
'''


def test_keeps_two_reads_across_a_scoped_call():
    [(family, child)] = variants(SOURCE, 'f', 'mips', ASM)
    assert family == FAMILY
    assert 'do { __repair_byte_table = options; } while (0);' in child
    assert 'do { send(channel); } while (0);' in child
    assert child.count('__repair_byte_table[0]') == 2


def test_requires_the_same_target_pointer_and_a_safe_insertion_site():
    assert not variants(SOURCE, 'f', 'mips', ASM.replace('nop\nlbu $v0, 0($s2)', 'nop\nlbu $v0, 0($s3)'))
    assert not variants(SOURCE.replace('if (options', 'if (ready) if (options', 1), 'f', 'mips', ASM)
    assert not variants(SOURCE.replace('extern u8', 'extern volatile u8'), 'f', 'mips', ASM)
