from decomprepair.loop_sentinel_repairs import FAMILY, variants

SOURCE = """int f(unsigned short *p) {
    if (*p != 0xFFFF) {
        do {
            if (*p == 2) return 1;
            p++;
        } while (*p != 65535U);
    }
    return 0;
}
"""
ASSEMBLY = """ori $v0, $zero, 0xffff
beq $a1, $v0, .Lexit
nop
ori $a2, $zero, 0xffff
.Lloop:
lhu $a1, 0($a0)
bne $a1, $a2, .Lloop
nop
.Lexit:
jr $ra
nop
"""


def test_guarded_loop_stages_the_sentinel_when_the_target_reloads_it():
    [(family, code)] = variants(SOURCE, 'f', '', 'mips', ASSEMBLY)
    assert family == FAMILY
    assert 'if (*p != 0xFFFF) {\n        unsigned repair_sentinel = 0xFFFF;' in code
    assert '} while (*p != repair_sentinel);' in code
    assert not variants(SOURCE, 'f', '', 'mips', ASSEMBLY.replace('ori $a2, $zero, 0xffff', 'nop'))
    assert not variants(SOURCE, 'f', '', 'mips', ASSEMBLY.replace('bne $a1, $a2', 'bne $a1, $v0'))
    assert not variants(SOURCE.replace('        do', 'entry:\n        do'), 'f', '', 'mips', ASSEMBLY)
    assert not variants(SOURCE, 'f', '', 'ppc', ASSEMBLY)
