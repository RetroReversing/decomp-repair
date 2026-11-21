from decomprepair import frame_padding_repairs as repairs

CALLER = '''glabel f
/* 0 80000000 27BDFFC8 */  addiu      $sp, $sp, -0x38
/* 4 80000004 AFB5002C */  sw         $s5, 0x2C($sp)
/* 8 80000008 AFB00018 */  sw         $s0, 0x18($sp)
/* c 8000000c AFBF0030 */  sw         $ra, 0x30($sp)
/* 10 80000010 0C000000 */  jal        g
'''
SOURCE = 'void f(void) {\n    g();\n}\n'


def test_the_bytes_between_the_argument_area_and_the_saved_registers_are_a_local():
    assert repairs.padding(CALLER) == 8
    (family, text), = repairs.variants(SOURCE, 'f', CALLER)
    assert family == repairs.FAMILY and 'volatile u64 scratch;' in text


def test_stack_arguments_and_a_leaf_frame_are_accounted_for():
    with_args = CALLER + '/* 14 80000014 AFA00010 */  sw         $zero, 0x10($sp)\n/* 18 80000018 AFA00014 */  sw $zero, 0x14($sp)\n'
    assert repairs.padding(with_args) == 0  # the five-word argument area fills the gap
    leaf = CALLER.replace('jal        g', 'jr $ra')
    assert repairs.padding(leaf) == 0x18


def test_a_draft_with_stack_locals_or_a_scratch_already_is_left_alone():
    for body in ('    volatile u64 scratch;\n    g();\n', '    s32 sp18;\n    g(&sp18);\n'):
        assert repairs.variants('void f(void) {\n' + body + '}\n', 'f', CALLER) == []


def test_a_frame_with_no_extra_bytes_has_no_candidate():
    exact = CALLER.replace('0x18($sp)', '0x10($sp)')
    assert repairs.padding(exact) == 0 and repairs.variants(SOURCE, 'f', exact) == []
