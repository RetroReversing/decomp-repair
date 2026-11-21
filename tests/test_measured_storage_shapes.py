from decomprepair import measured_storage_shapes as repairs


def rows_for(operations, changes):
    return [('r', op, changes[i]) if i in changes else (' ', op, op) for i, op in enumerate(operations)]


def test_pointer_advance_reuses_the_recorded_local():
    source = '''void f(void *state) {
    void *cursor;
    cursor = M2C_FIELD(state, void **, 20);
    M2C_FIELD(cursor, s32 *, 0) = value;
    M2C_FIELD(cursor, s32 *, 4) = 0;
    M2C_FIELD(state, void **, 20) = (void *) (M2C_FIELD(state, void **, 20) + 8);
}
'''
    operations = [
        'lw $v1, 20($a0)', 'sw $a1, 0($v1)', 'sw $zero, 4($v1)', 'lw $v0, 20($a0)',
        'addiu $v1, $v0, 8', 'jr $ra', 'sw $v1, 20($a0)',
    ]
    changes = {4: 'addiu $v0, $v0, 8', 6: 'sw $v0, 20($a0)'}
    rows = rows_for(operations, changes)
    [(family, fixed)] = repairs.variants(source, 'f', '', rows, '', big_endian=True)
    assert family == 'staged_pointer_advance'
    assert 'cursor = M2C_FIELD(state, void **, 20) + 8;\n    M2C_FIELD(state, void **, 20) = cursor;' in fixed
    assert not repairs.variants(source.replace('+ 8', '+ 16'), 'f', '', rows, '', big_endian=True)
    escaped = source.replace('    M2C_FIELD(cursor, s32 *, 0)', '    save(&cursor);\n    M2C_FIELD(cursor, s32 *, 0)')
    assert not repairs.variants(escaped, 'f', '', rows, '', big_endian=True)
    wrong = rows_for(operations, changes | {6: 'sw $v0, 24($a0)'})
    assert not repairs.variants(source, 'f', '', wrong, '', big_endian=True)


def test_word_copy_precedes_binding_the_loop_cursor():
    source = '''void f(void *out, void *in) {
    void *cursor;
    cursor = in;
    M2C_FIELD(out, s32 *, 16) = (s32) M2C_FIELD(in, s32 *, 8);
    send(cursor);
}
'''
    ops = ['move $t0, $zero', 'sw $v0, 12($t1)', 'lw $v0, 8($a1)',
           'move $a3, $a1', 'move $a2, $a0', 'sw $v0, 16($t1)', 'lw $v0, 12($a3)']
    changes = {0: ops[3], 2: 'lw $v0, 8($a3)', 3: ops[0]}
    rows = rows_for(ops, changes)
    [(family, fixed)] = repairs.variants(source, 'f', '', rows, '', big_endian=True)
    assert family == 'cursor_after_word_copy'
    assert fixed.index('M2C_FIELD(out, s32 *, 16)') < fixed.index('cursor = in;')
    assert not repairs.variants(source.replace('FIELD(in', 'FIELD(cursor'), 'f', '', rows, '', big_endian=True)
    assert not repairs.variants(source.replace('    cursor = in;', '    if (ready)\n        cursor = in;'),
                                'f', '', rows, '', big_endian=True)


def test_wide_timer_return_requires_both_adjacent_return_stores():
    source = '''s32 osGetTime(); /* extern */
void f(void) {
    s32 result;
    if (ready) {
        result = osGetTime();
        M2C_FIELD(&state, s32 *, 32) = result;
        M2C_FIELD(&state, u32 *, 36) = (u32) (u64) result;
    }
}
'''
    target = ['jal osGetTime', 'nop', 'lui $at, %hi(state + 0x20)', 'sw $v0, %lo(state + 0x20)($at)',
              'lui $at, %hi(state + 0x24)', 'sw $v1, %lo(state + 0x24)($at)']
    rows = rows_for(target, {5: 'sw $v0, %lo(state + 0x24)($at)'})

    def annotate(ops):
        return '\n'.join(f'/* {i:06X} {0x80000000+4*i:08X} 00000000 */ {op}' for i, op in enumerate(ops))

    asm = annotate(target)
    [(family, fixed)] = repairs.variants(source, 'f', '', rows, asm, big_endian=True)
    assert family == 'wide_sdk_return_store'
    assert 'long long osGetTime(void);' in fixed
    assert 'M2C_FIELD(&state, long long *, 32) = osGetTime();' in fixed
    assert 'result' not in fixed
    assert not repairs.variants(source, 'f', '', rows, asm, big_endian=False)
    assert not repairs.variants(source.replace('*, 36)', '*, 40)'), 'f', '', rows, asm, big_endian=True)
    assert not repairs.variants(source, 'f', 's32 osGetTime(void);', rows, asm, big_endian=True)
    clobbered = annotate([*target[:4], 'li $v1, 3', target[5]])
    assert not repairs.variants(source, 'f', '', rows, clobbered, big_endian=True)


def test_repeated_global_byte_offsets_follow_the_measured_stride():
    source = """extern s16 key;
extern s32 first, second;
void f(void) {
    s32 initial;
    s32 reload;
    initial = key * 4;
    use(*(s32 *)((s8 *)&first + initial));
    reload = key * 0x4;
    use(*(s32 *)((s8 *)&second + reload));
}
"""
    operations = ['sll $v1, $v0, 4', 'lw $a0, 0($v1)', 'sll $v0, $v0, 0x4']
    changes = {0: 'sll $v1, $v0, 2', 2: 'sll $v0, $v0, 2'}
    rows = rows_for(operations, changes)
    results = repairs.variants(source, 'f', '', rows, '', big_endian=True)
    assert results == [('measured_byte_offset_scale', source.replace('key * 4', 'key * 16')
                        .replace('key * 0x4', 'key * 16'))]
    for unrelated in (source.replace('use(*(s32 *)((s8 *)&second + reload));', 'use(reload);'),
                      source.replace('reload = key', 'reload = other')):
        assert not repairs.variants(unrelated, 'f', '', rows, '', big_endian=True)
    mismatched = rows_for(operations, changes | {2: 'sll $v0, $v1, 2'})
    assert not repairs.variants(source, 'f', '', mismatched, '', big_endian=True)
