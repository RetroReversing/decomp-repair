from decomprepair import out_of_line_guard_repairs as guard
from decomprepair import target_call_constant_repairs as constant

ASM = """beqz $v0, .Lelse
addiu $a0, $zero, 64
lw $a1, 4($s0)
j .Lcall
nop
.Lelse:
lw $a1, 8($s0)
.Lcall:
jal send
nop
"""
SOURCE = """void f(int flag) {
    if (flag) { send(91, 2); }
    else { send(91, 3); }
    n = 91;
}
"""


def test_call_constant_uses_common_delay_slot_and_only_changes_arguments():
    assert constant.variants(SOURCE, 'f', ASM) == [
        (constant.FAMILY, SOURCE.replace('send(91', 'send(64'))
    ]
    assert not constant.variants(SOURCE, 'f', ASM.replace('lw $a1, 8($s0)', 'lw $a0, 8($s0)'))
    assert not constant.variants(SOURCE, 'f', 'b .Lcall\nnop\n' + ASM)
    assert not constant.variants(SOURCE, 'f', ASM.replace('jal send\nnop', 'jal send\nmove $a0, $s0'))


def test_out_of_line_guard_keeps_failure_action_and_existing_cleanup():
    source = """void f(int fail) {
    if (fail) { state = 0; goto clean; }
    work();
clean:
    pending = 0;
}
"""
    [(family, rewritten)] = guard.variants(source, 'f')
    assert family == guard.FAMILY
    assert 'if (fail) { goto decomp_failure; }' in rewritten
    assert 'work();\n    goto clean;\ndecomp_failure:\n    state = 0;\nclean:' in rewritten
    assert not guard.variants(source.replace('state = 0; ', ''), 'f')
    assert not guard.variants(source.replace('    work();', '    int state = 1;\n    work();'), 'f')
