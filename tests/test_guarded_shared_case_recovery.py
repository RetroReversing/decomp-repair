from decomprepair import guarded_shared_case_recovery as repair

ASM = '''addiu $v0, $zero, 0x90
beq $v1, $v0, .L90
nop
addiu $v0, $zero, 0x80
beq $v1, $v0, .L80
nop
.L90:
andi $s1, $s0, 0xff
beqz $s1, .Lguard
nop
j .Lend
nop
.Lguard:
move $a0, $s2
.L80:
move $a1, $s3
jal find_voice
nop
.Lend:
nop
'''
SOURCE = '''void f(int event, int velocity) {
    switch (event) {
    case 0x90:
        if (velocity != 0) { play(); } else { stop(); }
        break;
    case 0xa0:
        other(); break;
    }
}
'''


def test_recovers_direct_dispatch_to_guarded_else():
    assert repair.evidence(ASM) == [(0x90, 0x80)]
    out = repair.variants(SOURCE, 'f', ASM)
    assert len(out) == 1
    assert 'case 0x80:' in out[0][1]
    assert 'if (velocity != 0) { play(); \n            break;' in out[0][1]
    assert '{ stop(); }' in out[0][1]


def test_requires_a_target_guard_and_shared_call():
    assert not repair.variants(SOURCE, 'f', ASM.replace('beqz $s1', 'bnez $s1'))
    assert not repair.variants(SOURCE, 'f', ASM.replace('jal find_voice', 'j find_voice'))
    assert not repair.variants(SOURCE.replace('case 0xa0:', 'case 0x80:'), 'f', ASM)


def test_rejects_unrelated_or_ambiguous_dispatch():
    assert not repair.variants(SOURCE, 'f', ASM.replace('beq $v1, $v0, .L80', 'beq $a3, $v0, .L80'))
    assert not repair.variants(SOURCE.replace('if (velocity != 0)', 'if (velocity == 0)'), 'f', ASM)
    assert not repair.variants(SOURCE.replace('stop();', 'goto label;'), 'f', ASM)
