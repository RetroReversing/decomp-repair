import pytest

from decomprepair.targeted_switch_labels import zero_bound_variants

ASM = """lui $v0, %hi(mode)
lw $v0, %lo(mode)($v0)
addiu $sp, $sp, -0x18
addiu $v1, $v0, -1
sltiu $v0, $v1, 4
beqz $v0, .Lexit
sw $ra, 0x10($sp)
sll $v0, $v1, 2
lui $at, %hi(table)
addu $at, $at, $v0
lw $v0, %lo(table)($at)
jr $v0"""
SOURCE = """extern int mode;
int run(volatile unsigned int unused, int option) {
    int value;
    switch (mode) {
    case 0: break;
    case 1:
        switch (option) { default: return 3; }
        break;
    case 4: return 4;
    }
    return 0;
}"""


def test_combines_one_based_bound_and_unused_home_store():
    [(family, candidate)] = zero_bound_variants(SOURCE, 'run', ASM)
    assert family == 'switch_zero_bound'
    assert 'run(unsigned int unused, int option)' in candidate
    assert 'case 0:' not in candidate
    assert 'case 1:' in candidate and 'default: return 3;' in candidate


@pytest.mark.parametrize('source,asm', [
    (SOURCE.replace('return 0;', 'return unused;'), ASM),
    (SOURCE.replace('case 4: return 4;', 'case 4: return 4; default: return 5;'), ASM),
    (SOURCE.replace('case 0: break;', 'case 0: return 9;'), ASM),
    (SOURCE.replace('case 4:', 'case 3:'), ASM),
    (SOURCE, ASM.replace('sw $ra,', 'sw $a0,')),
    (SOURCE, ASM.replace('%lo(mode)', '%lo(other)')),
])
def test_requires_an_inert_case_and_unused_qualifier_with_matching_table(source, asm):
    assert zero_bound_variants(source, 'run', asm) == []
