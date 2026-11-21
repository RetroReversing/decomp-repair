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


def test_combines_uniform_frame_growth_with_evidenced_forwarding():
    source = '''int get();
void f(int context, int value) {
    get(value);
}
'''
    rows = [
        ('s', 'addiu $sp, $sp, -32', 'addiu $sp, $sp, -24'),
        ('s', 'sw $ra, 24($sp)', 'sw $ra, 16($sp)'),
        (' ', 'jal get', 'jal get'),
        ('r', 'move $a1, $a1', 'move $a0, $a1'),
        ('s', 'lw $ra, 24($sp)', 'lw $ra, 16($sp)'),
        (' ', 'jr $ra', 'jr $ra'),
        ('s', 'addiu $sp, $sp, 32', 'addiu $sp, $sp, 24'),
    ]
    asm = '\n'.join(row[1] for row in rows)
    [(family, fixed)] = repairs.forwarded_variants(source, 'f', '', rows, asm, 8)
    assert family == 'frame_reservation_with_forwarded_argument'
    assert 'volatile u64 scratch;' in fixed and 'get(context, value);' in fixed
    assert not repairs.forwarded_variants(source, 'f', '', rows, asm, 16)
    assert not repairs.forwarded_variants(source, 'f', 'int get(int);', rows, asm, 8)
    assert not repairs.forwarded_variants(source.replace('get(value);', 'int sp18;\n    get(value);'), 'f', '', rows, asm, 8)
    wrong_restore = [*rows[:4], ('s', 'lw $ra, 24($sp)', 'lw $ra, 20($sp)'), *rows[5:]]
    assert not repairs.forwarded_variants(source, 'f', '', wrong_restore, asm, 8)
