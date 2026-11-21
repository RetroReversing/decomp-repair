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


def test_float_output_wrapper_passes_the_pointer_kept_live_through_initialization():
    source = '''
M2C_UNK init();  /* extern */
void f(void *out, f32 x, f32 y, f32 z) {
    init();
    M2C_FIELD(out, f32 *, 0) = x;
    M2C_FIELD(out, f32 *, 20) = y;
    M2C_FIELD(out, f32 *, 40) = z;
    M2C_FIELD(out, f32 *, 60) = 1.0f;
}
'''
    code = [
        'addiu $sp, $sp, -48',
        'sdc1 $f20, 24($sp)', 'mtc1 $a1, $f20',
        'sdc1 $f22, 32($sp)', 'mtc1 $a2, $f22',
        'sw $s0, 16($sp)',
        'sdc1 $f24, 40($sp)', 'mtc1 $a3, $f24',
        'sw $ra, 20($sp)',
        'jal init', 'move $s0, $a0',
        'lui $at, 0x3f80', 'mtc1 $at, $f0',
        'swc1 $f20, ($s0)', 'swc1 $f22, 20($s0)', 'swc1 $f24, 40($s0)', 'swc1 $f0, 60($s0)',
    ]
    rows = [(' ', i, i) for i in code]
    rows[5] = ('o', code[5], '')
    rows.insert(8, ('o', '', code[5]))
    asm = '\n'.join(code)
    [(family, fixed)] = p.shifted_call_variants(source, 'f', '', asm, rows)
    assert family == 'passthrough_argument'
    assert 'init(out);' in fixed
    assert not p.shifted_call_variants(source, 'f', 'int init(void);', asm, rows)
    assert not p.shifted_call_variants(source, 'f', '', 'move $a0, $zero\n' + asm, rows)
    assert not p.shifted_call_variants(source.replace('40) = z', '44) = z'), 'f', '', asm, rows)
    assert not p.shifted_call_variants(source.replace('40) = z', '40) = y'), 'f', '', asm, rows)


def test_missing_entry_context_is_restored_along_with_the_callee_prototype():
    source = '''
M2C_UNK callee(void *); /* extern */
s32 f(void) {
    callee(&object);
    return 0;
}
'''
    rows = [
        (' ', 'jal callee', 'jal callee'),
        ('r', 'move $a1, $s0', 'move $a0, $s0'),
    ]
    asm = 'jal callee\nmove $a1, $s0'
    [(family, fixed)] = p.shifted_call_variants(source, 'f', '', asm, rows)
    assert family == 'passthrough_argument'
    assert 'f(s32 __repair_incoming)' in fixed
    assert 'callee(s32, void *);' in fixed
    assert 'callee(__repair_incoming, &object);' in fixed
    assert not p.shifted_call_variants(source, 'f', '', 'li $a0, 9\n' + asm, rows)
    assert not p.shifted_call_variants(source, 'f', 'void callee(void *);', asm, rows)
    assert not p.shifted_call_variants(source.replace('/* extern */', ''), 'f', '', asm, rows)


def test_missing_entry_argument_requires_a0_unchanged_on_both_sides_of_a_branch():
    source = '''
M2C_UNK set_mode(M2C_UNK); /* extern */
s32 f(void) {
    s32 mode;
    if (flag) mode = 1;
    else mode = 0;
    set_mode(mode);
    return 0;
}
'''
    instructions = [
        'bnez $v0, .Lyes', 'nop',
        'j .Lcall', 'move $a1, $zero',
        '.Lyes:', 'addiu $a1, $zero, 1',
        '.Lcall:', 'jal set_mode', 'nop', 'jr $ra', 'nop',
    ]
    def annotate(items):
        output = []
        pc = 0
        for item in items:
            if item.endswith(':'):
                output.append(item)
            else:
                output.append(f'/* {pc:06X} {0x80000000+pc:08X} 00000000 */ {item}')
                pc += 4
        return '\n'.join(output)
    rows = [
        (' ', 'bnez $v0, .Lyes', 'bnez $v0, .Lyes'),
        (' ', 'nop', 'nop'),
        (' ', 'j .Lcall', 'j .Lcall'),
        ('r', 'move $a1, $zero', 'move $a0, $zero'),
        ('r', 'addiu $a1, $zero, 1', 'addiu $a0, $zero, 1'),
        (' ', 'jal set_mode', 'jal set_mode'),
        (' ', 'nop', 'nop'),
    ]
    [(family, fixed)] = p.shifted_call_variants(source, 'f', '', annotate(instructions), rows)
    assert family == 'passthrough_argument'
    assert 'set_mode(__repair_incoming, mode);' in fixed
    clobber = instructions[:]
    clobber[1] = 'move $a0, $zero'
    assert not p.shifted_call_variants(source, 'f', '', annotate(clobber), rows)
    repeat = instructions[:-2] + ['j .Lcall', 'nop']
    assert not p.shifted_call_variants(source, 'f', '', annotate(repeat), rows)


def test_shifted_memset_wrapper_restores_destination_parameter():
    source = '''
M2C_UNK memset(M2C_UNK, M2C_UNK); /* extern */
void f(M2C_UNK arg1, M2C_UNK arg2) {
    memset(arg2, arg1);
}
'''
    target = [
        'addiu $sp, $sp, -24', 'sw $ra, 16($sp)', 'move $v0, $a1', 'move $a1, $a2',
        'jal memset', 'move $a2, $v0', 'lw $ra, 16($sp)', 'jr $ra', 'addiu $sp, $sp, 24',
    ]
    rows = [(' ', text, text) for text in target]
    for i, changed in ((2, 'move $v0, $a0'), (3, 'move $a0, $a1'), (5, 'move $a1, $v0')):
        rows[i] = ('r', target[i], changed)
    [(family, fixed)] = p.shifted_call_variants(source, 'f', '', '\n'.join(target), rows)
    assert family == 'passthrough_argument'
    assert 'void f(void *__repair_incoming, M2C_UNK arg1, M2C_UNK arg2)' in fixed
    assert 'memset(__repair_incoming, arg2, arg1);' in fixed
    assert not p.shifted_call_variants(source.replace('memset(arg2, arg1);', 'memset(arg1, arg2);'),
                                       'f', '', '\n'.join(target), rows)


def test_local_call_group_keeps_context_when_later_code_differs():
    source = '''
M2C_UNK bind(void *, s32); /* extern */
void f(void *obj, s32 (*callback)(void *)) {
    bind(&table, 7);
    callback(obj);
}
'''
    rows = [
        (' ', 'move $s0, $a0', 'move $s0, $a0'),
        ('r', 'lui $a1, %hi(table)', 'lui $a0, %hi(table)'),
        ('r', 'addiu $a1, $a1, %lo(table)', 'addiu $a0, $a0, %lo(table)'),
        (' ', 'jal bind', 'jal bind'),
        ('r', 'addiu $a2, $zero, 7', 'addiu $a1, $zero, 7'),
        ('i', 'addiu $v0, $zero, 12', 'addiu $v0, $zero, 8'),
        (' ', 'jalr $s3', 'jalr $s3'),
        (' ', 'move $a0, $s0', 'move $a0, $s0'),
    ]
    asm = '\n'.join(row[1] for row in rows)
    [(family, fixed)] = p.shifted_call_variants(source, 'f', '', asm, rows)
    assert family == 'passthrough_argument'
    assert 'bind(obj, &table, 7);' in fixed
    assert '(*callback)(void *)' in fixed
    assert not p.shifted_call_variants(source, 'f', '', 'move $a0, $zero\n' + asm, rows)


def test_repeated_callee_repairs_only_the_first_short_call():
    source = '''
s32 search(); /* extern */
s32 f(s32 context) {
    if (search(1)) return 1;
    return search(context, 2);
}
'''
    target = ['jal search', 'addiu $a1, $zero, 1', 'jal search', 'nop', 'jr $ra', 'nop']
    asm = '\n'.join(f'/* {i*4:06X} {0x80000000+i*4:08X} 00000000 */ {op}' for i, op in enumerate(target))
    rows = [(' ', op, op) for op in target]
    rows[1] = ('r', target[1], 'addiu $a0, $zero, 1')
    [(family, fixed)] = p.shifted_call_variants(source, 'f', '', asm, rows)
    assert family == 'passthrough_argument'
    assert fixed == source.replace('search(1)', 'search(context, 1)')
    assert not p.shifted_call_variants(source.replace('search(context, 2)', 'search(2)'), 'f', '', asm, rows)
    assert not p.shifted_call_variants(source.replace('search(1)', 'search(3)'), 'f', '', asm, rows)


def test_shifted_call_uses_only_paths_that_reach_the_selected_case():
    source = '''
s32 left();
s32 right();
void f(int context, int flags) {
    switch (mode) {
    case 0:
        left(context, flags & 0xFFFF);
        return;
    case 1:
        right(flags & 0xFFFF);
        return;
    }
}
'''
    target = [
        'bnez $v0, .Lright', 'nop',
        'jal left', 'andi $a1, $a1, 0xFFFF',
        'j .Lend', 'nop',
        'jal right', 'andi $a1, $a1, 0xFFFF',
        'jr $ra', 'nop',
    ]
    labels = {6: '.Lright:\n', 8: '.Lend:\n'}

    def assembly(instructions):
        return '\n'.join(f'{labels.get(i, "")}/* {i*4:06X} {0x80000000+i*4:08X} 00000000 */ {op}'
                         for i, op in enumerate(instructions))

    rows = [(' ', op, op) for op in target]
    rows[7] = ('r', target[7], 'andi $a0, $a1, 0xFFFF')
    [(family, fixed)] = p.shifted_call_variants(source, 'f', '', assembly(target), rows)
    assert family == 'passthrough_argument'
    assert 'right(context, flags & 0xFFFF);' in fixed
    assert 'left(context, flags & 0xFFFF);' in fixed

    # A live predecessor that called left, or a delay-slot write on the path
    # to right, destroys the evidence for forwarding the entry argument.
    assert not p.shifted_call_variants(source, 'f', '', assembly(target[:4]+['j .Lright']+target[5:]), rows)
    assert not p.shifted_call_variants(source, 'f', '', assembly(target[:1]+['move $a0, $zero']+target[2:]), rows)
    annulled = ['beqzl $v0, .Lend', 'move $a0, $zero', 'j .Lright', 'nop', *target[4:]]
    assert p.shifted_call_variants(source, 'f', '', assembly(annulled), rows)


def test_shifted_global_word_load_restores_missing_formal():
    source = '''
s32 allocate(s32); /* extern */
extern s32 capacity;
s32 f(void) {
    result = allocate(capacity);
    return 0;
}
'''
    rows = [
        ('r', 'lui $a1, %hi(capacity)', 'lui $a0, %hi(capacity)'),
        ('r', 'lw $a1, %lo(capacity)($a1)', 'lw $a0, %lo(capacity)($a0)'),
        (' ', 'jal allocate', 'jal allocate'),
        (' ', 'nop', 'nop'),
    ]
    asm = '\n'.join(row[1] for row in rows)
    [(family, fixed)] = p.shifted_call_variants(source, 'f', '', asm, rows)
    assert family == 'passthrough_argument'
    assert 's32 f(s32 __repair_incoming)' in fixed
    assert 's32 allocate(s32, s32);' in fixed
    assert 'result = allocate(__repair_incoming, capacity);' in fixed

    for load in ('lw $a0, %lo(capacity)($a1)', 'lw $a0, %lo(other)($a0)'):
        bad_rows = [rows[0], ('r', rows[1][1], load), *rows[2:]]
        assert not p.shifted_call_variants(source, 'f', '', asm, bad_rows)
    assert not p.shifted_call_variants(source, 'f', 's32 allocate(s32);', asm, rows)


def test_forward_a_missing_argument_when_a_byte_reload_and_earlier_calculation_are_shifted():
    source = '''M2C_UNK send(u8); /* extern */
s32 f(void) {
    send(read_byte());
    return 0;
}
'''
    target = ['lbu $a1, 8($v1)', 'andi $v0, $a1, 0xff', 'addiu $v0, $a1, 1',
              'jal send', 'lbu $a1, 8($v0)', 'jr $ra', 'nop']
    edits = {0: 'lbu $a0, 8($v1)', 1: 'andi $v0, $a0, 0xff', 2: 'addiu $v0, $a0, 1', 4: 'lbu $a0, 8($v0)'}
    rows = [('r', op, edits[i]) if i in edits else (' ', op, op) for i, op in enumerate(target)]
    asm = '\n'.join(target)
    [(family, fixed)] = p.shifted_call_variants(source, 'f', '', asm, rows)
    assert family == 'passthrough_argument'
    assert 'send(__repair_incoming, read_byte());' in fixed
    assert not p.shifted_call_variants(source, 'f', '', 'move $a0, $zero\n'+asm, rows)
    rows[0] = ('r', 'lbu $a1, 16($v1)', 'lbu $a0, 16($v1)')
    assert not p.shifted_call_variants(source, 'f', '', asm, rows)


def test_halfword_reload_supports_the_same_proven_argument_forwarding():
    source = '''M2C_UNK send(u16); /* extern */
s32 f(void) {
    send(read_word());
    return 1;
}
'''
    target = ['lhu $a1, 8($v1)', 'slt $v0, $a1, $v0', 'addiu $v0, $a1, 1',
              'jal send', 'lhu $a1, 8($v0)', 'jr $ra', 'nop']
    rows = [('r', op, op.replace('$a1', '$a0')) if '$a1' in op else (' ', op, op) for op in target]
    asm = '\n'.join(target)
    [(family, fixed)] = p.shifted_call_variants(source, 'f', '', asm, rows)
    assert family == 'passthrough_argument'
    assert 'send(__repair_incoming, read_word());' in fixed
    rows[0] = ('r', 'lbu $a1, 8($v1)', 'lbu $a0, 8($v1)')
    assert not p.shifted_call_variants(source, 'f', '', asm, rows)


def _guarded_halfword(guard, delta, *, subtract=False, update_first=False):
    mask = 'andi $a1, $a1, 0xffff'
    condition = 'beqz $a1, .Lreturn' if guard == '!= 0' else 'sltiu $v0, $a1, 2'
    branch = [condition]
    if guard != '!= 0':
        branch.append(f"{'bnez' if subtract else 'beqz'} $v0, .Lreturn")
    load = '    old = M2C_FIELD(state, u16 *, 12);'
    update = f"    next = old {'-' if delta < 0 else '+'} 1;"
    setup = '\n'.join((update, load) if update_first else (load, update))
    value = '(next & 0xffff) - 1' if subtract else 'next & 0xffff'
    source = f'''M2C_UNK send(s32); /* extern */
s32 step(void) {{
    u16 old;
    u16 next;
{setup}
    if (old {guard}) {{
        M2C_FIELD(state, u16 *, 12) = next;
        send({value});
    }}
    return 0;
}}
'''
    slot = 'addiu $a1, $a1, -1' if subtract else mask
    call = ['sh $a1, 12($v1)', *([mask] if subtract else []), 'jal send', slot]
    target = ['lw $v1, 8($s0)', 'lhu $a1, 12($v1)', *branch, f'addiu $a1, $a1, {delta}', *call,
              '.Lreturn:', 'move $v0, $zero', 'jr $ra', 'nop']
    rows = [('r', op, op.replace('$a1', '$a0')) if op == slot else (' ', op, op)
            for op in target if not op.endswith(':')]
    instructions = iter(range(len(rows)))
    asm = '\n'.join(op if op.endswith(':') else
                    f'/* 000000 {0x80000000+4*next(instructions):08X} 00000000 */ {op}' for op in target)
    return source, asm, rows


def test_guarded_halfword_restores_forwarding_and_sinks_update_after_load():
    for guard, delta, subtract, first in (('!= 0', -1, False, False), ('< 2U', 1, False, True),
                                         ('>= 2U', -1, True, True)):
        source, asm, rows = _guarded_halfword(guard, delta, subtract=subtract, update_first=first)
        [(family, fixed)] = p.shifted_call_variants(source, 'step', '', asm, rows)
        assert family == p.FAMILY
        assert 's32 step(s32 __repair_incoming)' in fixed
        assert 'send(s32, s32);' in fixed
        assert f"if (old {guard}) {{\n        next = old {'-' if delta < 0 else '+'} 1;" in fixed
        assert fixed.count('next = old') == 1
        assert 'send(__repair_incoming, ' in fixed


def test_guarded_halfword_requires_same_field_and_unchanged_first_argument():
    source, asm, rows = _guarded_halfword('< 2U', 1)
    for bad_asm in (asm.replace('sh $a1, 12', 'sh $a1, 14'),
                    asm.replace('lw $v1, 8($s0)', 'move $a0, $zero\nlw $v1, 8($s0)'),
                    asm.replace('.Lreturn\n', '.Lstore\n').replace('/* 000000 80000014', '.Lstore:\n/* 000000 80000014')):
        assert not p.shifted_call_variants(source, 'step', '', bad_asm, rows)
    bad_source = source.replace('old < 2U', 'old < 3U')
    assert not p.shifted_call_variants(bad_source, 'step', '', asm, rows)
    assert not p.shifted_call_variants(source, 'step', 'void send(s32);', asm, rows)


def test_forward_pointer_and_keep_the_result_in_the_argument_local():
    source = '''void *lookup(s32); /* extern */
void update(void *context) {
    s32 item;
    void *result;
    item = M2C_FIELD(M2C_FIELD(context, void **, 8), s32 *, 12);
    if (item != 0) {
        result = lookup(item);
        if (result != NULL) {
            M2C_FIELD(context, void **, 24) = M2C_FIELD(result, void **, 16);
        }
    }
}
'''
    target = [
        'move $s0, $a0', 'lw $v0, 8($s0)', 'lw $a1, 12($v0)', 'beqz $a1, .Lend', 'nop',
        'jal lookup', 'nop', 'move $a1, $v0', 'beqz $a1, .Lend', 'nop',
        'lw $v0, 16($a1)', 'sw $v0, 24($s0)', 'jr $ra', 'nop',
    ]
    candidate = {2: 'lw $a0, 12($v0)', 3: 'beqz $a0, .Lend', 7: 'move $v1, $v0',
                 8: 'beqz $v1, .Lend', 10: 'lw $v0, 16($v1)'}
    rows = [('r', op, candidate[i]) if i in candidate else (' ', op, op) for i, op in enumerate(target)]

    def assembly(ops):
        lines = [f'/* {i * 4:06X} {0x80000000 + i * 4:08X} 00000000 */ {op}' for i, op in enumerate(ops)]
        lines.insert(12, '.Lend:')
        return '\n'.join(lines)

    asm = assembly(target)
    [(family, fixed)] = p.shifted_call_variants(source, 'update', '', asm, rows)
    assert family == p.FAMILY
    assert 'lookup(void *, void *);' in fixed
    assert 'item = lookup(context, item);' in fixed
    assert 'M2C_FIELD(item, void **, 16)' in fixed
    assert 'result' not in fixed
    assert not p.shifted_call_variants(source, 'update', 'void *lookup(s32);', asm, rows)
    assert not p.shifted_call_variants(source, 'update', '', assembly([*target[:4], 'move $a0, $zero', *target[5:]]),
                                       rows)
    for edited in (source.replace('**, 16)', '**, 20)'),
                   source.replace('= M2C_FIELD(result, void **, 16);', '= M2C_FIELD(result, void **, 16);\n use(item);')):
        assert not p.shifted_call_variants(edited, 'update', '', asm, rows)


def test_float_call_forwards_entry_argument_before_stack_output():
    source = ('f32 distance(u16 *); /* extern */\n'
              'void f(s32 item) {\n    u16 marker;\n'
              '    f32 result;\n    result = distance(&marker);\n    save(result, item);\n}')
    target = ['addiu $sp, $sp, -0x18', 'sw $ra, 0x14($sp)', 'jal distance',
              'addiu $a1, $sp, 0x10', 'jal save', 'nop',
              'lw $ra, 0x14($sp)', 'jr $ra', 'addiu $sp, $sp, 0x18']
    rows = [('r', op, op.replace('$a1', '$a0')) if i == 3 else (' ', op, op)
            for i, op in enumerate(target)]
    asm = '\n'.join(target)
    [(family, fixed)] = p.shifted_call_variants(source, 'f', '', asm, rows)
    assert family == p.FAMILY
    assert 'f32 distance(s32, u16 *);' in fixed
    assert 'distance(item, &marker);' in fixed
    implicit = source.replace('s32 item', 'void').replace('save(result, item)', 'save(result)')
    [(_, fixed)] = p.shifted_call_variants(implicit, 'f', '', asm, rows)
    assert 'void f(s32 __repair_incoming)' in fixed
    assert 'distance(__repair_incoming, &marker);' in fixed
    assert not p.shifted_call_variants(source, 'f', '', 'move $a0, $zero\n' + asm, rows)
    assert not p.shifted_call_variants(source, 'f', 'f32 distance(s32, u16 *);', asm, rows)
    raw_asm = asm.replace('jal distance', 'jal func_80001234')
    assert not p.shifted_call_variants(source, 'f', '', raw_asm, rows)
    assert p.shifted_call_variants(source, 'f', '', raw_asm, rows, resolve={'distance': 0x80001234}.get)

    for formals, expected_type in [('f32 *item', 'f32 *'), ('s32 item, u32 limit', 's32')]:
        typed = source.replace('s32 item', formals)
        [(_, fixed)] = p.shifted_call_variants(typed, 'f', '', asm, rows)
        assert f'f32 distance({expected_type}, u16 *);' in fixed
        assert f'void f({formals})' in fixed
        assert 'distance(item, &marker);' in fixed
    assert not p.shifted_call_variants(source.replace('s32 item', 'f32 item'), 'f', '', asm, rows)
    assert p.shifted_call_variants(source, 'f', 'void f(s32 item);', asm, rows)
    assert not p.shifted_call_variants(implicit, 'f', 'void f(void);', asm, rows)


def test_forward_second_entry_argument_when_float_literal_moves_to_third_slot():
    source = ('typedef s32 M2C_UNK;\nM2C_UNK show(M2C_UNK, f32); /* extern */\n'
              'void f(void *p, M2C_UNK target) { show(0, 0.5f); }')
    target = ['sw $ra, 0x14($sp)', 'lui $a2, 0x3f00', 'lw $s1, 0x20($s0)',
              'jal show', 'move $a0, $zero', 'jr $ra', 'nop']
    rows = [('r', op, op.replace('$a2', '$a1')) if i == 1 else (' ', op, op)
            for i, op in enumerate(target)]
    raw = '\n'.join(target).replace('jal show', 'jal func_80002000')
    resolve = {'show': 0x80002000}.get
    header = 'typedef int s32;'
    [(_, fixed)] = p.shifted_call_variants(source, 'f', header, raw, rows, resolve=resolve)
    assert 'show(M2C_UNK, M2C_UNK, f32)' in fixed
    assert 'show(0, target, 0.5f)' in fixed
    assert not p.shifted_call_variants(source, 'f', header, raw, rows)
    assert not p.shifted_call_variants(source, 'f', header, 'move $a1, $zero\n' + raw, rows, resolve=resolve)
    assert not p.shifted_call_variants(source.replace('0.5f', '1.0f'), 'f', header, raw, rows, resolve=resolve)
