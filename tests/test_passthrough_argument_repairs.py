"""The caller's own parameter passed on to a callee m2c gave one argument too few."""
from decomprepair import passthrough_argument_repairs as p

SOURCE = '''s32 g();
s32 h(s32, s32);

s32 f(s32 arg0, void *arg1, s32 arg2) {
    if (D != NULL) {
        g(arg0, D, M2C_FIELD(arg1, s32 *, 0xC), M2C_FIELD(arg1, s32 *, 0x24));
        return 1;
    }
    h(arg0, arg2);
    return 0;
}
'''


def test_each_parameter_at_its_own_position():
    # An N64 function at 95%: the game called g(arg0, D, arg2, ...), its $a2 untouched; exact so.
    calls = [text[text.index('        g('):text.index(';', text.index('        g('))] for _, text in p.variants(SOURCE, 'f')]
    assert '        g(arg0, D, arg2, M2C_FIELD(arg1, s32 *, 0xC), M2C_FIELD(arg1, s32 *, 0x24))' in calls
    assert '        g(arg0, arg1, D, M2C_FIELD(arg1, s32 *, 0xC), M2C_FIELD(arg1, s32 *, 0x24))' in calls


def test_a_prototype_is_widened_with_the_call():
    texts = [t for _, t in p.variants(SOURCE.replace('s32 g();', 's32 g(s32, void *, s32, s32);'), 'f')]
    assert any('s32 g(s32, void *, s32, s32, s32);' in t and 'g(arg0, D, arg2, M2C_FIELD' in t for t in texts)
    assert all(t.count('g(') == 2 for t in texts)  # the prototype and the one call


def test_a_prototyped_callee_gains_the_parameter():
    # Three N64 functions called f32 g(u16 *) as g(arg0, &sp10): exact with the prototype widened.
    source = 'f32 g(u16 *);\nvoid f(s32 arg0) {\n    u16 sp10;\n\n    h(g(&sp10), arg0);\n}\n'
    texts = [t for _, t in p.variants(source, 'f')]
    assert any('f32 g(s32, u16 *);' in t and 'g(arg0, &sp10)' in t for t in texts)
    twice = source.replace('h(g(&sp10), arg0);', 'h(g(&sp10), g(&sp10));')
    assert not any('f32 g(s32, u16 *);' in t for _, t in p.variants(twice, 'f'))


def test_a_callee_given_no_arguments_gets_all_of_the_callers_at_once():
    # (an N64 function: `f()` 40 points off, exact as `f(arg0, arg1, arg2)`)
    source = ('s32 func_8007A974();\n'
              's32 func_8007AA40(void *arg0, s32 arg1, s32 *arg2) {\n'
              '    func_8007A974();\n'
              '    return *arg2;\n'
              '}\n')
    texts = [t for _, t in p.variants(source, 'func_8007AA40')]
    assert any('func_8007A974(arg0, arg1, arg2);' in t for t in texts)


def test_literal_wrapper_restores_the_unwritten_incoming_argument():
    source = '''M2C_UNK g(M2C_UNK); /* extern */
void f(void) {
    g(2);
}
'''
    asm = '''addiu $sp, $sp, -0x18
sw $ra, 0x10($sp)
jal g
addiu $a1, $zero, 0x2
lw $ra, 0x10($sp)
jr $ra
addiu $sp, $sp, 0x18
'''
    fixed = p.missing_entry_argument(source, 'f', asm)
    assert fixed
    assert 'M2C_UNK g(s32, M2C_UNK);' in fixed
    assert 'void f(s32 arg0)' in fixed
    assert 'g(arg0, 2);' in fixed
    assert p.missing_entry_argument(source, 'f', asm.replace('0x2\n', '3\n')) is None
    assert p.missing_entry_argument(source, 'f', asm.replace('$a1', '$a0')) is None
    assert p.missing_entry_argument(source, 'f', asm, 'void g(s32);') is None
    assert p.missing_entry_argument(source.replace('g(2)', 'g(0)'), 'f',
                                    asm.replace('addiu $a1, $zero, 0x2', 'addu $a1, $zero, $zero'))
    assert p.missing_entry_argument(source.replace('g(2)', 'g(-1)'), 'f', asm.replace(' 0x2\n', ' -0x1\n'))


def test_address_wrapper_can_have_a_second_call_after_forwarding_the_first_argument():
    source = '''M2C_UNK load(M2C_UNK *); /* extern */
extern M2C_UNK table;
void f(void) {
    load(&table);
    finish();
}
'''
    asm = '''addiu $sp, $sp, -24
sw $ra, 16($sp)
lui $a1, %hi(table)
jal load
addiu $a1, $a1, %lo(table)
jal finish
nop
lw $ra, 16($sp)
jr $ra
addiu $sp, $sp, 24
'''
    fixed = p.missing_entry_argument(source, 'f', asm)
    assert fixed
    assert 'M2C_UNK load(s32, M2C_UNK *);' in fixed
    assert 'void f(s32 arg0)' in fixed
    assert 'load(arg0, &table);\n    finish();' in fixed
    assert p.missing_entry_argument(source, 'f', asm.replace('lui $a1', 'lui $a0')) is None
    assert p.missing_entry_argument(source, 'f', asm.replace('jal finish', 'jal cleanup')) is None
    assert p.missing_entry_argument(source, 'f', asm, 'void load(void *);') is None


def test_wrapper_can_forward_a_parameter_before_a_field_loaded_in_the_delay_slot():
    source = '''M2C_UNK read(s32); /* extern */
extern void *state;
void f(void) {
    read(M2C_FIELD(state, s32 *, 12));
}
'''
    asm = '''lui $v0, %hi(state)
lw $v0, %lo(state)($v0)
addiu $sp, $sp, -24
sw $ra, 16($sp)
jal read
lw $a1, 0xC($v0)
lw $ra, 16($sp)
jr $ra
addiu $sp, $sp, 24
'''
    patch = p.missing_entry_argument(source, 'f', asm)
    assert patch
    assert 'M2C_UNK read(s32, s32);' in patch
    assert 'read(arg0, M2C_FIELD(state, s32 *, 12));' in patch
    assert p.missing_entry_argument(source.replace('*, 12', '*, 16'), 'f', asm) is None


def test_zero_fill_wrapper_recovers_the_destination_parameter():
    source = '''M2C_UNK memset(M2C_UNK, M2C_UNK); /* extern */
void f(void) {
    memset(0, 24);
}
'''
    asm = '''addiu $sp, $sp, -24
sw $ra, 16($sp)
move $a1, $zero
jal memset
addiu $a2, $zero, 0x18
lw $ra, 16($sp)
jr $ra
addiu $sp, $sp, 24
'''
    patch = p.missing_entry_argument(source, 'f', asm)
    assert patch
    assert 'void f(void *arg0)' in patch
    assert 'memset(arg0, 0, 24);' in patch
    assert p.missing_entry_argument(source.replace('0, 24', '1, 24'), 'f', asm) is None
    assert p.missing_entry_argument(source.replace('0, 24', '0, 12'), 'f', asm) is None


def test_shifted_call_prioritizes_only_the_untouched_first_parameter():
    source = '''s32 read();
void f(int id, void *object) {
    read(M2C_FIELD(object, s32 *, 8));
}
'''
    rows = [
        (' ', 'jal read', 'jal read'),
        ('r', 'lw $a1, 8($a1)', 'lw $a0, 8($a1)'),
    ]
    asm = 'jal read\nlw $a1, 8($a1)'
    [(family, patch)] = p.shifted_call_variants(source, 'f', '', asm, rows)
    assert family == 'passthrough_argument'
    assert 'read(id, M2C_FIELD(object, s32 *, 8));' in patch
    assert not p.shifted_call_variants(source, 'f', '', 'move $a0, $zero\n'+asm, rows)
    assert not p.shifted_call_variants(source, 'f', '', asm, [
        rows[0], ('r', 'lw $a1, 8($a1)', 'lw $a0, 12($a1)'),
    ])
    assert not p.shifted_call_variants(source, 'f', 's32 read(s32);', asm, rows)


def test_shifted_call_counts_paired_address_relocations_as_single_arguments():
    source = '''
s32 bind(void *, void *, s32);
void f(void *context) {
    bind(&pull, &update, 7);
    touch(context);
}
'''
    rows = [
        ('r', 'lui $a1, %hi(pull)', 'lui $a0, %hi(pull)'),
        ('r', 'addiu $a1, $a1, %lo(pull)', 'addiu $a0, $a0, %lo(pull)'),
        ('r', 'lui $a2, %hi(update)', 'lui $a1, %hi(update)'),
        ('r', 'addiu $a2, $a2, %lo(update)', 'addiu $a1, $a1, %lo(update)'),
        (' ', 'sw $ra, 20($sp)', 'sw $ra, 20($sp)'),
        (' ', 'jal bind', 'jal bind'),
        ('r', 'addiu $a3, $zero, 7', 'addiu $a2, $zero, 7'),
    ]
    asm = '\n'.join(a for _, a, _ in rows)
    [(family, fixed)] = p.shifted_call_variants(source, 'f', '', asm, rows)
    assert family == 'passthrough_argument'
    assert 'bind(void *, void *, void *, s32)' in fixed
    assert 'bind(context, &pull, &update, 7);' in fixed
    invalid = [
        rows[:1] + [('r', rows[1][1], 'addiu $a0, $a0, %lo(update)')] + rows[2:],
        rows[:2] + [('r', 'lui $a2, %hi(other)', 'lui $a1, %hi(other)')] + rows[3:],
        rows[:1] + [('r', rows[1][1], 'addiu $a0, $t0, %lo(pull)')] + rows[2:],
    ]
    for case in invalid:
        assert not p.shifted_call_variants(source, 'f', '', asm, case)
    assert not p.shifted_call_variants(source, 'f', '', 'move $a0, $zero\n' + asm, rows)
