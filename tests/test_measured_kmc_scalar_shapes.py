from decomprepair.measured_kmc_scalar_shapes import variants


def measured(ops):
    return [(' ', op, op) for op in ops]


def test_two_halfword_stores_reuse_the_mask():
    source = '''
void f(void *obj, s32 index, s32 x, s32 y) {
    s32 offset;
    offset = (index & 0xFFFF) * 8;
    M2C_FIELD((offset + M2C_FIELD(obj, s32 *, 16)), s16 *, 4) = (s16) ((x & 0xFFFF) << 3);
    M2C_FIELD((offset + M2C_FIELD(obj, s32 *, 16)), s16 *, 6) = (s16) ((y & 0xFFFF) << 3);
}
'''
    rows = measured((
        'lw $v0, 16($a0)', 'andi $a1, $a1, 65535', 'sll $a1, $a1, 3',
        'andi $a2, $a2, 65535', 'sll $a2, $a2, 3', 'addu $v0, $a1, $v0', 'sh $a2, 4($v0)',
        'lw $v0, 16($a0)', 'andi $a3, $a3, 65535', 'sll $a3, $a3, 3', 'addu $a1, $a1, $v0',
        'jr $ra', 'sh $a3, 6($a1)',
    ))
    for index in (3, 8):
        rows[index] = ('<', rows[index][1], '')
    [(family, fixed)] = variants(source, 'f', '', rows)
    assert family == 'measured_shared_halfword_mask'
    assert fixed.count('& __repair_shared_halfword_mask') == 3
    assert not variants(source.replace('6) =', '8) ='), 'f', '', rows)


def test_early_zero_return_for_integer_sqrt_uses_measured_hardware_path():
    rows = measured((
        'bltz $a0, 32', 'move $v0, $zero', 'mtc1 $a0, $f0', 'nop', 'cvt.s.w $f0, $f0',
        'sqrt.s $f0, $f0', 'trunc.w.s $f2, $f0', 'mfc1 $v0, $f2', 'jr $ra', 'nop',
    ))
    rows[1] = ('r', rows[1][1], 'move $v1, $zero')
    rows.insert(8, ('o', '', 'nop'))
    source = '''
s32 f(s32 x) {
    s32 result;
    result = 0;
    if (x >= 0) { result = (s32) sqrtf((f32) x); }
    return result;
}
'''
    [(family, fixed)] = variants(source, 'f', '', rows, flags=('-ffast-math',))
    assert family == 'measured_early_integer_sqrt'
    assert 'if (x < 0) return 0;' in fixed and '__builtin_sqrtf' in fixed
    assert not variants(source, 'f', '', rows)
    assert not variants(source.replace('result = 0', 'result = -1'), 'f', '', rows, flags=('-ffast-math',))


def test_unsigned_halfword_literal_keeps_the_positive_immediate():
    rows = measured((
        'lui $v0, %hi(slots)', 'lw $v0, %lo(slots)($v0)', 'andi $a0, $a0, 255',
        'sll $a0, $a0, 1', 'addu $a0, $a0, $v0', 'ori $v0, $zero, 65535',
        'jr $ra', 'sh $v0, 24($a0)',
    ))
    rows[5] = ('|', rows[5][1], 'addiu $v0, $zero, -1')
    source = '''
void f(s32 index) {
    M2C_FIELD((((index & 0xFF) * 2) + slots), s16 *, 24) = 0xFFFF;
}
'''
    [(family, fixed)] = variants(source, 'f', '', rows)
    assert family == 'measured_indexed_unsigned_halfword_store'
    assert 'slots), u16 *, 24)' in fixed
    assert not variants(source.replace('24)', '20)'), 'f', '', rows)


def test_clear_loop_casts_the_address_when_target_clears_words():
    rows = measured((
        'move $v1, $zero', 'lui $a0, %hi(table)', 'addiu $a0, $a0, %lo(table)',
        'andi $v0, $v1, 65535', 'sll $v0, $v0, 2', 'addu $v0, $v0, $a0', 'sw $zero, ($v0)',
        'addiu $v1, $v1, 1', 'andi $v0, $v1, 65535', 'sltiu $v0, $v0, 16',
        'bnel $v0, $zero, 16', 'andi $v0, $v1, 65535', 'jr $ra', 'nop',
    ))
    rows[6] = ('|', rows[6][1], 'sb $zero, ($v0)')
    source = '''
void f(void) {
    s32 index;
    index = 0;
    do {
        *(((index & 0xFFFF) * 4) + ((char *)&state + 32)) = 0;
        index += 1;
    } while ((u32) (index & 0xFFFF) < 16U);
}
'''
    resolve = {'table': 0x80001020, 'state': 0x80001000}.get
    [(family, fixed)] = variants(source, 'f', '', rows, resolve=resolve)
    assert family == 'measured_word_clear_loop'
    assert '*(s32 *)(((index & 0xFFFF) * 4)' in fixed
    assert not variants(source, 'f', '', rows)
    assert not variants(source.replace('< 16U', '< 32U'), 'f', '', rows, resolve=resolve)


def test_word_load_recovers_byte_pointer_table():
    rows = measured((
        'beqz $a0, 32', 'addiu $v0, $zero, 1', 'sll $v0, $a0, 2',
        'lui $at, %hi(base)', 'addu $at, $at, $v0', 'lw $v0, %lo(base)($at)',
        'addu $v0, $v0, $a1', 'lbu $v0, ($v0)', 'jr $ra', 'andi $v0, $v0, 255',
    ))
    rows[5] = ('|', rows[5][1], 'lb $v0, %lo(base)($at)')
    source = '''
extern char base[];
s32 f(s32 row, s32 col) {
    u8 value;
    value = 1;
    if (row != 0) { value = *(u8 *)(*(base + (row * 4)) + col); }
    return value & 0xFF;
}
'''
    [(family, fixed)] = variants(source, 'f', '', rows)
    assert family == 'measured_byte_pointer_table'
    assert 'extern u8 * base[];' in fixed and 'value = base[row][col];' in fixed
    assert not variants(source, 'f', 'extern char base[];', rows)


def test_byte_case_guard_restores_input_width_and_preserves_result_type():
    rows = measured((
        'addiu $v0, $a0, -48', 'andi $v0, $v0, 255', 'sltiu $v0, $v0, 10', 'bnez $v0, 28',
        'move $v1, $a0', 'j f+36', 'andi $v0, $v1, 255', 'addiu $v0, $a0, 32',
        'andi $v0, $v0, 255', 'jr $ra', 'nop',
    ))
    for i in (4, 5, 6, 7):
        rows[i] = ('r', rows[i][1], 'different')
    source = '''
s32 f(s32 input) {
    if ((u32) ((input - 48) & 0xFF) >= 10U) { goto keep; }
    return (input + 32) & 0xFF;
keep: { return input & 0xFF; }
}
'''
    [(family, fixed)] = variants(source, 'f', '', rows)
    assert family == 'measured_narrow_case_byte'
    assert 's32 f(char input)' in fixed and 'return (u8)input;' in fixed
    assert not variants(source, 'f', 's32 f(s32 input);', rows)


def test_masked_pointer_search_uses_word_table_entries():
    from decomprepair.measured_kmc_scalar_shapes import variants

    source = '''
u8 f(s32 wanted) {
    s32 index;
    s32 found;
    void *entry;
    index = 0;
    found = 0;
    do {
        entry = *(((index & 0xFFFF) * 4) + ((char *)&owner + 16));
        if ((entry != NULL) && (M2C_FIELD(entry, s32 *, 4) == wanted)) { found = 1; }
        index += 1;
    } while (!found);
    return 0;
}
'''
    ops = [
        'move $t0, $zero', 'move $a2, $zero', 'lui $t1, %hi(table)',
        'addiu $t1, $t1, %lo(table)', 'andi $v0, $a2, 65535',
        'sll $v0, $v0, 2', 'addu $v0, $v0, $t1', 'lw $a1, ($v0)',
        'beql $a1, $zero, 56', 'addiu $a2, $a2, 1', 'lw $v0, 4($a1)',
        'beql $v0, $a0, 52', 'addiu $t0, $zero, 1',
    ]
    rows = [(' ', op, op) for op in ops] + [(' ', 'nop', 'nop')] * 16
    rows[0] = ('r', ops[0], ops[1])
    rows[1] = ('r', ops[1], ops[0])
    rows[7] = ('|', ops[7], 'lb $a1, ($v0)')
    symbols = {'owner': 100, 'table': 116}
    [(label, fixed)] = variants(source, 'f', '', rows, resolve=symbols.get)
    assert label == 'measured_masked_pointer_search'
    assert 'entry = *(void **)' in fixed
    assert not variants(source, 'f', '', rows, resolve={'owner': 100, 'table': 120}.get)
    assert not variants(source.replace('0xFFFF) * 4', '0xFFFF) * 8'), 'f', '', rows, resolve=symbols.get)


def test_masked_pointer_search_restores_bounded_loop_for_both_byte_updates():
    from decomprepair.measured_kmc_scalar_shapes import variants

    source = '''u8 f(s32 wanted) {
        s32 test;
        s32 index;
        s32 found;
        void *entry;
        index = 0;
        found = 0;
        do {
            entry = *(((index & 0xFFFF) * 4) + ((char *)&owner + 16));
            if ((entry != NULL) && (M2C_FIELD(entry, s32 *, 4) == wanted)) { found = 1; }
            index += 1;
            test = found & 0xFF;
        } while ((test == 0) & ((u32) (index & 0xFFFF) < 0x800U));
        if (test != 0) {
            M2C_FIELD(entry, u8 *, 2) = (u8) (M2C_FIELD(entry, u8 *, 2) + 1);
        }
        return M2C_FIELD(entry, u8 *, 2);
    }'''
    ops = ['move $t0, $zero', 'move $a2, $zero', 'lui $t1, %hi(table)',
           'addiu $t1, $t1, %lo(table)', 'andi $v0, $a2, 65535', 'sll $v0, $v0, 2',
           'addu $v0, $v0, $t1', 'lw $a1, ($v0)', 'beql $a1, $zero, 56', 'addiu $a2, $a2, 1',
           'lw $v0, 4($a1)', 'beql $v0, $a0, 52', 'addiu $t0, $zero, 1',
           'sltiu $v0, $v0, 2048', 'addiu $v0, $v0, 1']
    rows = [(' ', op, op) for op in ops] + [(' ', 'nop', 'nop')] * 14
    rows[0] = ('r', ops[0], ops[1])
    rows[1] = ('r', ops[1], ops[0])
    rows[7] = ('|', ops[7], 'lb $a1, ($v0)')
    symbols = {'owner': 100, 'table': 116}
    for op, immediate in [('+', '1'), ('-', '-1')]:
        text = source.replace('2) + 1)', f'2) {op} 1)')
        diff = [(tag, left.replace('addiu $v0, $v0, 1', f'addiu $v0, $v0, {immediate}'), right)
                for tag, left, right in rows]
        candidates = dict(variants(text, 'f', '', diff, resolve=symbols.get))
        fixed = candidates['measured_masked_pointer_loop']
        assert 'u16 index;' in fixed
        assert fixed.index('found = 0;') < fixed.index('index = 0;')
        assert f'2) {op} 1)' in fixed
    assert 'measured_masked_pointer_loop' not in dict(variants(source.replace('0x800U', '0x10000U'), 'f', '', rows, resolve=symbols.get))
    assert 'measured_masked_pointer_loop' not in dict(variants(source, 'f', '#define found other', rows, resolve=symbols.get))
