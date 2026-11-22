from decomprepair.mips import prepared_call_arguments
from decomprepair.near_match_repairs import variants


def test_argument_before_switch_dispatch_cannot_justify_forwarding_at_handler_call():
    asm = """
    addu $a3, $zero, $zero
    lw $v0, 0($at)
    jr $v0
    nop
    lh $v0, 4($s0)
    bne $v0, $s1, .Ldone
    addu $a0, $s3, $zero
    jal callee
    addu $a1, $s0, $zero
    """
    source = "int callee(void *, void *); int f(void *x, void *y) { return callee(y, x); }"
    assert prepared_call_arguments(asm, 'callee') == 2
    assert variants(source, 'f', asm) == []


def test_branch_likely_delay_slot_does_not_execute_on_fallthrough():
    asm = "bnel $v0, $zero, .Ldone\nmove $a3, $s0\njal callee\nmove $a0, $s1"
    assert prepared_call_arguments(asm, 'callee') == 1


def test_a_prior_call_can_clobber_argument_registers():
    asm = "jal other\nmove $a3, $s0\njal callee\nmove $a0, $s1"
    assert prepared_call_arguments(asm, 'callee') == 1


def test_straight_line_setup_and_call_delay_slot_count():
    asm = "move $a2, $s0\njal callee\nmove $a3, $s1"
    assert prepared_call_arguments(asm, 'callee') == 4
