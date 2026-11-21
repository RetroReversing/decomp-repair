from decomprepair.direct_mapped_address import applies, rewrite

ASM = '''
addiu $sp, $sp, -24
lui $v1, 0x1fff
ori $v1, $v1, 0xffff
lui $v0, 0x8000
subu $v0, $a0, $v0
sltu $v0, $v1, $v0
beqz $v0, .Ldirect
sw $ra, 16($sp)
lui $v0, 0x6000
addu $v0, $a0, $v0
sltu $v0, $v1, $v0
beqz $v0, .Lexit
and $v0, $a0, $v1
jal slow_lookup
nop
j .Lexit
nop
.Ldirect:
and $v0, $a0, $v1
.Lexit:
lw $ra, 16($sp)
jr $ra
addiu $sp, $sp, 24
'''
SOURCE = '''
s32 slow_lookup();
s32 translate(s32 addr) {
    s32 result;
    if ((u32) (addr - 0x80000000) > 0x1FFFFFFFU) {
        result = addr & 0x1FFFFFFF;
        if ((u32) (addr + 0x60000000) > 0x1FFFFFFFU) {
            return slow_lookup();
        }
        return result;
    }
    result = addr & 0x1FFFFFFF;
    return result;
}
'''


def test_direct_ranges_remain_independent_and_the_fallback_receives_the_address():
    assert applies(ASM)
    candidate = rewrite(SOURCE, 'translate', ASM)
    assert candidate
    assert candidate.count('return addr & 0x1FFFFFFF;') == 2
    assert '((u32)addr - 0x80000000U)' in candidate
    assert '((u32)addr + 0x60000000U)' in candidate
    assert 'return slow_lookup(addr);' in candidate
    assert rewrite(SOURCE, 'translate', ASM.replace('sltu $v0', 'slt $v0')) is None
    assert rewrite(SOURCE, 'translate', ASM.replace('jal slow_lookup\nnop', 'jal slow_lookup\nmove $a0, $zero')) is None
    assert rewrite(SOURCE, 'translate', ASM, 's32 slow_lookup(void);') is None
