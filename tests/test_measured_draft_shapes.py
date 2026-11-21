"""Exercise the measured draft repairs through their shared app entry point."""

from decomprepair import measured_storage_shapes


def _run(source, target, candidate, asm='', header=''):
    rows = [('r', row, candidate[i]) if i in candidate else (' ', row, row) for i, row in enumerate(target)]
    return measured_storage_shapes.variants(source, 'update', header, rows, asm, big_endian=True)


def test_reassociate_an_indexed_byte_bias_only_for_the_measured_field_loads():
    source = '''s32 update(void *left, void *right) {
    s32 value;
    value = M2C_FIELD(((M2C_FIELD(left, u8 *, 5) * 16) + M2C_FIELD(right, s32 *, 12)), u8 *, 8) + (M2C_FIELD(M2C_FIELD(left, void **, 4), u8 *, 3) - 64);
    return value;
}'''
    target = [
        'lbu $v1, 5($a0)', 'lw $v0, 12($a1)', 'lw $a0, 4($a0)', 'sll $v1, $v1, 4', 'addu $v1, $v1, $v0',
        'lbu $v0, 3($a0)', 'lbu $v1, 8($v1)', 'addiu $v0, $v0, -64', 'addu $v1, $v1, $v0',
    ]
    candidate = {0: 'lbu $v0, 5($a0)', 1: 'lw $v1, 12($a1)', 3: 'sll $v0, $v0, 4', 4: 'addu $v0, $v0, $v1',
                 5: 'lbu $v1, 8($v0)', 6: 'lbu $v0, 3($a0)', 7: 'addiu $v1, $v1, -64'}
    [(family, fixed)] = _run(source, target, candidate)
    assert family == 'indexed_byte_bias'
    assert '<< 4' in fixed
    assert 'u8 *, 8) - 64) + M2C_FIELD' in fixed
    assert not _run(source.replace('u8 *, 8)', 'u8 *, 9)'), target, candidate)
    assert not _run(source, target, candidate | {7: 'addiu $v1, $v1, -65'})


def test_hoist_only_the_incoming_mask_outside_the_list_back_edge():
    source = '''void update(s32 index) {
    s32 count;
    void *node;
    node = head;
    count = 0;
    if (node != NULL) {
loop:
        if ((count & 255) == (index & 255)) {
            M2C_FIELD(node, s32 *, 12) = (s32) (M2C_FIELD(node, s32 *, 12) | 2);
            return;
        }
        node = M2C_FIELD(node, void **, 4);
        count += 1;
        if (node == NULL) {
        } else {
            goto loop;
        }
    }
}
'''
    target = [
        'lw $v1, 4($v0)', 'beqz $v1, .Lend', 'move $a1, $zero', 'andi $a0, $a0, 255',
        'andi $v0, $a1, 255', 'bne $v0, $a0, .Lnext', 'nop', 'lw $v0, 12($v1)',
        'ori $v0, $v0, 2', 'j .Lend', 'sw $v0, 12($v1)', 'lw $v1, 4($v1)',
        'bnez $v1, .Lloop', 'addiu $a1, $a1, 1', 'jr $ra', 'nop',
    ]
    labels = {4: '.Lloop:\n', 11: '.Lnext:\n', 14: '.Lend:\n'}
    asm = '\n'.join(f'{labels.get(i, "")}/* {i*4:06X} {0x80000000+i*4:08X} 00000000 */ {op}'
                    for i, op in enumerate(target))
    candidate = {3: 'andi $v1, $a2, 255'}
    [(family, fixed)] = _run(source, target, candidate, asm)
    assert family == 'masked_list_index'
    assert '__repair_masked_index = index & 255;\nloop:' in fixed
    assert '(count & 255) == __repair_masked_index' in fixed
    assert 'if (node != NULL) {\n            goto loop;' in fixed
    assert not _run(source, target, candidate, asm.replace('andi $a0, $a0, 255', '.Lmask:\nandi $a0, $a0, 255')
                    .replace('bnez $v1, .Lloop', 'bnez $v1, .Lmask'))
    assert not _run(source.replace('count & 255', 'count & 127'), target, candidate, asm)


def test_recursive_count_is_forwarded_and_reused_on_both_early_returns():
    source = '''s32 count_items(); /* extern */
s32 update(s32 context) {
    s32 added;
    s32 count;
    s32 block;
    s32 result;
    count = count_items();
    result = count;
    if (count != 0) {
        block = reserve(context, count);
        result = count;
        if (block != 0) {
            added = count + update(context);
            release(block);
            result = added;
        }
    }
    return result;
}
'''
    target = [
        'addiu $sp, $sp, -32', 'sw $s1, 20($sp)', 'move $s1, $a0', 'sw $ra, 28($sp)', 'sw $s2, 24($sp)',
        'jal count_items', 'sw $s0, 16($sp)', 'move $s0, $v0', 'beqz $s0, .Lexit', 'move $v0, $s0',
        'move $a0, $s1', 'jal reserve', 'move $a1, $s0', 'move $s2, $v0', 'beqz $s2, .Lexit', 'move $v0, $s0',
        'jal update', 'move $a0, $s1', 'addu $s0, $s0, $v0', 'jal release', 'move $a0, $s2',
        'move $v0, $s0', 'lw $ra, 28($sp)', 'jr $ra', 'addiu $sp, $sp, 32',
    ]
    candidate = {18: 'addu $v0, $s0, $v0'}
    [(family, fixed)] = _run(source, target, candidate)
    assert family == 'recursive_call_accumulator'
    assert 'count = count_items(context);' in fixed
    assert 'count += update(context);\n            release(block);' in fixed
    assert 'return count;' in fixed
    assert not _run(source, target, candidate, header='s32 count_items(void);')
    assert not _run(source.replace('return result;', 'return result + block;'), target, candidate)
    assert not _run(source, [*target[:18], 'addu $s0, $s1, $v0', *target[19:]], candidate)
