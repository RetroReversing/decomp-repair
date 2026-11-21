from decomprepair import measured_storage_shapes as repairs


def annotate(text):
    return '\n'.join(f'/* {i*4:06X} {0x80000000+i*4:08X} 00000000 */ {op}'
                     for i, op in enumerate(text.strip().splitlines()))


def test_restore_byte_arithmetic_for_a_narrow_cosine_index():
    source = '''f32 __cosf(f32, s32); /* extern */
extern M2C_UNK records;
void f(s32 index) {
    s32 masked;
    void *record;
    masked = index & 0xFFFF;
    record = (masked * 100) + &records;
    M2C_FIELD(record, f32 *, 4) = __cosf(read(), masked);
}
'''
    target = '''andi $a0, $a0, 65535
sll $v0, $a0, 1
addu $v0, $v0, $a0
sll $v0, $v0, 3
addu $v0, $v0, $a0
sll $v0, $v0, 2
lui $v1, %hi(records)
addiu $v1, $v1, %lo(records)
addu $s0, $v0, $v1
jal __cosf
cvt.s.d $fa0, $fa0'''
    changed = (0, 1, 2, 4, 5)
    rows = [('r', op, op.replace('$a0', '$a1')) if i in changed else (' ', op, op)
            for i, op in enumerate(target.splitlines())]
    rows[0] = ('r', rows[0][1], 'andi $a1, $a0, 65535')
    rows[5] = ('r', rows[5][1], 'sll $v0, $v0, 4')
    asm = annotate(target)
    [(family, fixed)] = repairs.variants(source, 'f', '', rows, asm, big_endian=True)
    assert family == 'narrow_index_and_float_call'
    assert 'void f(u16 index)' in fixed and 'f32 __cosf(f32);' in fixed
    assert 'record = (index * 100) + (u8 *)&records;' in fixed
    assert '= __cosf(read());' in fixed
    assert not repairs.variants(source.replace('* 100', '* 200'), 'f', '', rows, asm, big_endian=True)
    assert not repairs.variants(source, 'f', '', rows, asm.replace('jal __cosf', 'jal other'), big_endian=True)
    assert not repairs.variants(source.replace('read()', 'read(masked)'), 'f', '', rows, asm, big_endian=True)


def test_callback_setup_preserves_two_distinct_base_lifetimes():
    source = '''extern void *state;
s32 f(void) {
    prepare();
    M2C_FIELD(state, s8 *, 2) = 0;
    M2C_FIELD(state, M2C_UNK **, 8) = &onStart;
    M2C_FIELD(state, M2C_UNK **, 12) = &onStop;
    M2C_FIELD(state, s8 *, 1) = -1;
    M2C_FIELD(state, s8 *, 3) = 0;
    return 0;
}
'''
    target = '''lui $v1, %hi(state)
lw $v1, %lo(state)($v1)
sb $zero, 2($v1)
lui $a0, %hi(state)
lw $a0, %lo(state)($a0)
lui $v0, %hi(onStart)
addiu $v0, $v0, %lo(onStart)
sw $v0, 8($v1)
lui $v0, %hi(onStop)
addiu $v0, $v0, %lo(onStop)
sw $v0, 12($v1)
addiu $v0, $zero, -1
sb $v0, 1($a0)
lui $v1, %hi(state)
lw $v1, %lo(state)($v1)
move $v0, $zero
sb $zero, 3($v1)'''
    rows = []
    for i, op in enumerate(target.splitlines()):
        candidate = op.replace('$v1', '$v0') if i < 3 else op.replace('$a0', '$v1') if i in (3, 4, 12) else op
        rows.append(('r' if op != candidate else ' ', op, candidate))
    asm = annotate(target)
    [(family, fixed)] = repairs.variants(source, 'f', '', rows, asm, big_endian=True)
    assert family == 'callback_reset_pointer_reloads'
    assert 'prepare();\n    __repair_reset_invalid = -1;' in fixed
    assert 'M2C_FIELD(__repair_reset_first, M2C_UNK **, 12) = &onStop;' in fixed
    assert 'M2C_FIELD(__repair_reset_second, s8 *, 1) = __repair_reset_invalid;' in fixed
    assert not repairs.variants(source, 'f', '', rows, asm.replace('%lo(onStop)', '%lo(onOther)'), big_endian=True)
    assert not repairs.variants(source.replace('s8 *, 3)', 's8 *, 5)'), 'f', '', rows, asm, big_endian=True)


def test_reload_the_stored_context_slot_through_its_address():
    source = '''extern void *context;
void update(void *input) {
    s32 saved;
    void *item;
    saved = begin_update();
    M2C_FIELD(context, void **, 12) = input;
    item = M2C_FIELD(context, void **, 12);
    M2C_FIELD(context, s16 *, 4) = 2;
    M2C_FIELD(context, s32 *, 16) = (s32) M2C_FIELD(item, s32 *, 8);
    end_update(saved, item);
}
'''
    target = [
        'sw $ra, 16($sp)', 'jal begin_update', 'move $s0, $a0', 'lui $a0, %hi(context)',
        'lw $a0, %lo(context)($a0)', 'sw $s0, 12($a0)', 'lw $a1, 12($a0)', 'addiu $v1, $zero, 2',
        'sh $v1, 4($a0)', 'lw $v1, 8($a1)', 'sw $v1, 16($a0)', 'jal end_update', 'move $a0, $v0',
        'jr $ra', 'nop',
    ]
    rows = [('r', op, 'move $a1, $s0') if op == 'lw $a1, 12($a0)' else (' ', op, op) for op in target]
    [(family, fixed)] = repairs.variants(source, 'update', '', rows, '\n'.join(target), big_endian=True)
    assert family == 'stored_context_slot_reload'
    assert '__repair_context_slot = &M2C_FIELD(context, void **, 12);' in fixed
    assert 'M2C_FIELD(__repair_context, s16 *, 4) = 2;\n    item = *__repair_context_slot;' in fixed
    assert 'end_update(saved, item);' in fixed
    assert not repairs.variants(source.replace('s16 *, 4) = 2', 's16 *, 6) = 2'),
                                                'update', '', rows, '\n'.join(target), big_endian=True)
