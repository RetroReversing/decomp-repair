"""Record layout and stack buffer regressions from measured KMC drafts."""

from decomprepair import measured_stack_drafts, measured_storage_shapes


def _matched(source, target, asm, edits):
    rows = [('r', op, edits[i]) if i in edits else (' ', op, op) for i, op in enumerate(target)]
    return measured_storage_shapes.variants(source, 'update', '', rows, asm, big_endian=True)


def test_scan_uses_byte_cursors_and_exits_immediately_after_the_store():
    source = '''void update(void *obj, s32 n, s32 key, s32 value) {
    s32 *record;
    s32 counter;
    void *entry;
    void *cell;

    entry = M2C_FIELD(obj, s32 *, 12) + ((n & 65535) * 20);
    record = M2C_FIELD(entry, s32 **, 8);
    counter = 0;
    if (M2C_FIELD(entry, u8 *, 12) != 0) {
        cell = record + 12;
again:
        if (*record != key) {
            counter += 1;
            goto advance;
        }
        if (M2C_FIELD(cell, s8 *, -8) != 0) {
            counter += 1;
advance:
            cell += 16;
            record += 16;
            if ((u32) (counter & 65535) >= (u8) M2C_FIELD(entry, u8 *, 12)) {
            } else {
                goto again;
            }
        } else {
            M2C_FIELD(cell, s32 *, 0) = value;
        }
    }
}'''
    target = [
        'andi $a1, $a1, 65535', 'sll $v0, $a1, 2', 'lw $v1, 12($a0)', 'addu $v0, $v0, $a1', 'sll $v0, $v0, 2',
        'addu $t1, $v1, $v0', 'lbu $v0, 12($t1)', 'lw $a1, 8($t1)', 'beqz $v0, .Lexit', 'move $t0, $zero',
        'addiu $a0, $a1, 12', 'lw $v0, 0($a1)', 'bnel $v0, $a2, .Lnext', 'addiu $t0, $t0, 1',
        'lb $v0, -8($a0)', 'bnel $v0, $zero, .Lnext', 'addiu $t0, $t0, 1', 'j .Lexit', 'sw $a3, 0($a0)',
        'addiu $a0, $a0, 16', 'lbu $v1, 12($t1)', 'andi $v0, $t0, 65535', 'sltu $v0, $v0, $v1',
        'bnez $v0, .Lloop', 'addiu $a1, $a1, 16', 'jr $ra', 'nop',
    ]
    labels = {11: '.Lloop:\n', 19: '.Lnext:\n', 25: '.Lexit:\n'}
    asm = '\n'.join(f'{labels.get(i, "")}/* {i*4:06X} {0x80000000+i*4:08X} 00000000 */ {op}'
                    for i, op in enumerate(target))
    edits = {10: 'addiu $a0, $a1, 48'}
    [(label, fixed)] = _matched(source, target, asm, edits)
    assert label == 'record_scan_byte_cursors'
    assert 'char *record;' in fixed and '__repair_scan_key = key;' in fixed
    assert 'M2C_FIELD(cell, s32 *, 0) = value;\n    return;' in fixed
    assert 'cell += 16;\n    record += 16;' in fixed
    assert not _matched(source.replace('goto again;', 'goto advance;'), target, asm, edits)
    assert not _matched(source, target, asm.replace('bnel $v0, $zero, .Lnext', 'bnel $v0, $zero, .Lexit'), edits)


def test_stage_the_layout_read_and_reuse_the_shared_constant():
    source = '''void update(void *obj) {
    void *row;
    M2C_FIELD(M2C_FIELD(obj, void **, 12), s32 *, 24) = 64;
    M2C_FIELD(M2C_FIELD(obj, void **, 12), s32 *, 28) = 64;
    M2C_FIELD(M2C_FIELD(obj, void **, 12), s32 *, 32) = (s32) (64 - M2C_FIELD(obj, s32 *, 8));
    row = M2C_FIELD(obj, void **, 12);
    M2C_FIELD(&state, s32 *, 12) = 0;
    M2C_FIELD(row, s32 *, 40) = (s32) (M2C_FIELD(row, s32 *, 8) + 6);
    M2C_FIELD(M2C_FIELD(obj, void **, 12), s32 *, 44) = (s32) (64 - M2C_FIELD(obj, s32 *, 8));
}'''
    target = [
        'addiu $a1, $zero, 64', 'lw $v1, 12($a0)', 'sw $a1, 24($v1)', 'lw $v1, 12($a0)', 'sw $a1, 28($v1)',
        'lw $v0, 8($a0)', 'subu $v0, $a1, $v0', 'lw $v1, 12($a0)', 'sw $v0, 32($v1)', 'lw $v1, 12($a0)',
        'lw $v0, 8($v1)', 'lui $at, %hi(reset)', 'sw $zero, %lo(reset)($at)', '',
        'addiu $v0, $v0, 6', 'sw $v0, 40($v1)', 'lw $v0, 8($a0)', 'subu $a1, $a1, $v0', 'lw $v1, 12($a0)',
        'sw $a1, 44($v1)', 'lw $v0, 16($a0)', 'jal finish', 'lw $a1, 8($v0)', 'jr $ra', 'nop',
    ]
    edits = {10: '', 13: 'lw $v0, 8($v1)'}
    [(label, fixed)] = _matched(source, target, '', edits)
    assert label == 'staged_layout_constant_and_load'
    assert '__repair_layout_limit = 64;' in fixed
    assert '__repair_layout_field = M2C_FIELD(row, s32 *, 8);\n    M2C_FIELD(&state' in fixed
    assert ' = (s32) (__repair_layout_field + 6);' in fixed
    assert not _matched(source.replace('s32 *, 40)', 's32 *, 36)'), target, '', edits)


def test_formatted_stack_bytes_share_one_buffer_after_the_clamp():
    source = '''void update(void) {
    u8 sp14;
    s32 value;
    value = read_count(context);
    to_buffer(&sp14, &format, value & ((s32) ~value >> 31) & 0xffff);
    a = sp14 - 48;
    if (sp15 != 0) b = sp15 - 48;
    if (sp16 != 0) c = sp16 - 48;
}'''
    asm = '''jal read_count
nop
nor $v1, $zero, $v0
sra $v1, $v1, 31
and $v0, $v0, $v1
addiu $a0, $sp, 20
lui $a1, %hi(format)
addiu $a1, $a1, %lo(format)
jal to_buffer
andi $a2, $v0, 65535
lbu $v0, 20($sp)
lbu $v0, 21($sp)
lbu $v0, 22($sp)
'''
    assert measured_stack_drafts.applies(asm)
    fixed = measured_stack_drafts.rewrite(source, 'update', asm)
    assert 'u8 __repair_format_bytes[4];' in fixed
    assert 'value &= (s32)~value >> 31;\n    to_buffer(__repair_format_bytes, &format, value & 0xFFFF);' in fixed
    assert 'c = __repair_format_bytes[2] - 48;' in fixed
    assert not measured_stack_drafts.rewrite(source, 'update', asm.replace('lbu $v0, 22', 'lw $v0, 22'))
    assert not measured_stack_drafts.rewrite(source.replace('c = sp16 - 48', 'c = &sp16'), 'update', asm)
