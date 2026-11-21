"""Check measured byte and word addressing through the shared draft entry points."""

from decomprepair import measured_storage_shapes, short_leaf_drafts


def _proposals(source, target, candidate, asm='', header=''):
    rows = [('r' if row != other else ' ', row, other) for row, other in zip(target, candidate, strict=True)]
    return measured_storage_shapes.variants(source, 'update', header, rows, asm, big_endian=True)


def test_guarded_counter_binds_both_relocations_and_stages_only_the_copy():
    source = '''void update(void) {
    if (M2C_FIELD(&counter, s32 *, 12) < M2C_FIELD(&state, s32 *, 8)) {
        if (M2C_FIELD(&counter, s32 *, 12) < 0) {
            M2C_FIELD(&counter, s32 *, 12) = 0;
        }
        M2C_FIELD(&state, s32 *, 8) = (s32) M2C_FIELD(&counter, s32 *, 12);
    }
}'''
    target = [
        'lui $a2, %hi(state + 8)', 'addiu $a2, $a2, %lo(state + 8)',
        'lui $v1, %hi(counter + 12)', 'addiu $v1, $v1, %lo(counter + 12)',
        'lw $a1, ($a2)', 'lw $a0, ($v1)', 'slt $v0, $a0, $a1', 'beqz $v0, .Lskip', 'nop',
        'bltzl $a0, .Lcopy', 'sw $zero, ($v1)', 'lui $v0, %hi(total)', 'lw $v0, %lo(total)($v0)',
        'lw $v1, ($v1)', 'addu $v0, $v0, $v1', 'lui $at, %hi(delta)', 'sw $v0, %lo(delta)($at)',
        'subu $v0, $a1, $v1', 'lui $at, %hi(gap)', 'sw $v0, %lo(gap)($at)', 'j .Lexit', 'sw $v1, ($a2)',
        'lui $at, %hi(gap)', 'sw $zero, %lo(gap)($at)', 'lui $v0, %hi(counter + 12)',
        'addiu $v0, $v0, %lo(counter + 12)', 'lw $v1, ($v0)', 'lui $a0, %hi(state + 8)',
        'lw $a0, %lo(state + 8)($a0)', 'subu $v1, $v1, $a0', 'jr $ra', 'sw $v1, ($v0)',
    ]
    actual = [target[i] for i in (2, 3, 0, 1, 5, 4)] + target[6:]
    [(family, fixed)] = _proposals(source, target, actual, '\n'.join(target))
    assert family == 'guarded_counter_address'
    assert 'if (M2C_FIELD(&state, s32 *, 8) > M2C_FIELD(&counter, s32 *, 12))' in fixed
    assert '__repair_counter_address = &M2C_FIELD(&counter, s32 *, 12);' in fixed
    assert ' = (s32) *__repair_counter_address;' in fixed
    assert not _proposals(source, target, actual, '\n'.join(target).replace('counter + 12', 'counter + 16'))


def test_only_first_indexed_byte_store_uses_the_staged_base():
    source = '''extern s32 state;
void update(s32 n) {
    s32 offset;
    offset = n * 20;
    M2C_FIELD((state + offset), s8 *, 12) = 3;
    M2C_FIELD((state + offset), s8 *, 14) = -1;
}
'''
    target = [
        'lui $v1, %hi(state)', 'lw $v1, %lo(state)($v1)', 'sll $a1, $a0, 2',
        'addu $a1, $a1, $a0', 'sll $a1, $a1, 2', 'addiu $v0, $zero, 3', 'addu $v1, $v1, $a1',
        'sb $v0, 12($v1)', 'lui $v0, %hi(state)', 'lw $v0, %lo(state)($v0)', 'addiu $a2, $zero, -1',
        'addu $v0, $v0, $a1', 'jr $ra', 'sb $a2, 14($v0)',
    ]
    want = ['', *target[:2], target[2], *target[3:]]
    have = [target[2], *target[:2], '', *target[3:]]
    [(family, fixed)] = _proposals(source, want, have, header='extern volatile s32 unrelated;')
    assert family == 'first_indexed_byte_base'
    assert 's32 __repair_first_store_base = state;' in fixed
    assert 'M2C_FIELD((__repair_first_store_base + offset), s8 *, 12)' in fixed
    assert 'M2C_FIELD((state + offset), s8 *, 14)' in fixed
    assert not _proposals(source, want, have, header='extern volatile s32 state;')
    assert not _proposals(source.replace(' * 20', ' * 24'), want, have)


def test_relocated_word_stores_keep_byte_stride_and_forward_the_input():
    values = {'red': 7, 'green': 21, 'blue': 126}
    globals_ = ''.join(f'extern M2C_UNK {symbol};\n' for symbol in values)
    stores = ''.join(f'    *(&{symbol} + offset) = {value};\n' for symbol, value in values.items())
    source = (f'M2C_UNK finish(M2C_UNK); /* extern */\n{globals_}void update(s32 n) {{\n'
              f'    s32 offset;\n    offset = n << 4;\n{stores}    finish(0);\n}}')
    target = ['addiu $sp, $sp, -24', 'sw $ra, 16($sp)', 'sll $v1, $a0, 4']
    for symbol, value in values.items():
        target += [f'addiu $v0, $zero, {value}', f'lui $at, %hi({symbol})', 'addu $at, $at, $v1',
                   f'sw $v0, %lo({symbol})($at)']
    target += ['jal finish', 'move $a1, $zero', 'lw $ra, 16($sp)', 'jr $ra', 'addiu $sp, $sp, 24']
    replacements = {'sll $v1, $a0, 4': 'sll $a0, $a0, 6', 'addu $at, $at, $v1': 'addu $at, $at, $a0',
                    'move $a1, $zero': 'move $a0, $zero'}
    actual = [replacements.get(row, row) for row in target]
    [(family, fixed)] = _proposals(source, target, actual, '\n'.join(target))
    assert family == 'relocated_indexed_word_stores'
    assert 'finish(n, 0);' in fixed
    for symbol, value in values.items():
        assert f'extern s32 {symbol};' in fixed
        assert f'*(s32 *)((u8 *)&{symbol} + offset) = {value};' in fixed
    assert not _proposals(source.replace('offset) = 21;', 'offset) = 22;'), target, actual, '\n'.join(target))
    assert not _proposals(source, target, actual, 'move $a0, $zero\n' + '\n'.join(target))


def test_indexed_leaf_repairs_untyped_deref_and_word_parameter_in_one_draft():
    source = '''void update(void *object, s32 index, s16 a, s16 b, u16 extra) {
    s32 offset;
    offset = (index & 0xffff) * 16;
    *(offset + M2C_FIELD(object, s32 *, 20)) = a;
    M2C_FIELD((offset + M2C_FIELD(object, s32 *, 20)), s16 *, 2) = b;
    M2C_FIELD((offset + M2C_FIELD(object, s32 *, 20)), u16 *, 4) = extra;
}'''
    asm = '''lw $v0, 20($a0)
andi $a1, $a1, 65535
sll $a1, $a1, 4
addu $v0, $a1, $v0
sh $a2, 0($v0)
lw $v0, 20($a0)
addu $v0, $a1, $v0
sh $a3, 2($v0)
lw $v0, 20($a0)
lhu $v1, 18($sp)
addu $a1, $a1, $v0
jr $ra
sh $v1, 4($a1)
'''
    assert short_leaf_drafts.applies(asm)
    [(family, fixed)] = short_leaf_drafts.variants(source, 'update', asm)
    assert family == 'indexed_stack_halfword'
    assert 'u16 index, s16 a, s16 b, s32 extra' in fixed
    assert '*(s16 *)(offset + M2C_FIELD' in fixed
    assert ' = ((u16 *)&extra)[1];' in fixed
    assert not short_leaf_drafts.variants(source, 'update', asm.replace('18($sp)', '16($sp)'))
    assert not short_leaf_drafts.variants(source, 'update', asm, 'void update(void *, s32, s16, s16, u16);')
